import json
import threading
import uuid
from flask import Flask, jsonify, request, send_from_directory
from .app import SYSTEM_PROMPT, compact_tool_result, embedded_call, memory_call, parse_args
from .config import load_config
from .knowledge import KnowledgeBase
from .ollama import OllamaClient
from .policy import Policy
from .ssh import SSHManager
from .tools import build_tools, command_for_tool

app=Flask(__name__,static_folder="web",static_url_path="")
config=load_config(); servers=config.get("servers",{}); ollama=OllamaClient(config); policy=Policy(config); ssh=SSHManager(config); knowledge=KnowledgeBase(config); tools=build_tools(servers); tool_names={t["function"]["name"] for t in tools}
agent=config.get("agent",{}); max_steps=int(agent.get("max_steps",32)); max_history=int(agent.get("max_history_messages",30))
_sessions={}; _pending={}; _lock=threading.RLock()

def _new_session():
    sid=uuid.uuid4().hex
    _sessions[sid]={"messages":[{"role":"system","content":SYSTEM_PROMPT+"\n\nCONFIGURED SERVERS:\n"+json.dumps(list(servers))+"\n\nRELEVANT MEMORY:\n"+knowledge.context("",None)}]}
    return sid

def _session(sid):
    with _lock:
        return sid if sid in _sessions else _new_session()

def _execute(server,command,tool_name):
    try:
        result=ssh.run(server,servers[server],command); result["ok"]=result.get("exit_code")==0; result["tool"]=tool_name; result["server"]=server; return result
    except Exception as exc:
        return {"ok":False,"exit_code":None,"error":f"{type(exc).__name__}: {exc}"}

def _run_turn(sid,user_text,approved_pending=None):
    messages=_sessions[sid]["messages"]
    messages.append({"role":"tool","content":json.dumps(approved_pending,ensure_ascii=False)} if approved_pending is not None else {"role":"user","content":user_text})
    for step in range(1,max_steps+1):
        result=ollama.chat(messages,tools); message=result.get("message",{}); calls=message.get("tool_calls") or []; content=(message.get("content") or "").strip()
        if not calls:
            recovered=embedded_call(content)
            if recovered: calls=[{"function":recovered}]
        messages.append(message)
        if not calls: return {"type":"answer","content":content,"step":step} if content else {"type":"error","content":"The model returned no answer or tool call.","step":step}
        function=calls[0].get("function",{}); name=function.get("name"); args=parse_args(function)
        if args is None: tool_result={"ok":False,"error":"Malformed tool arguments."}
        elif name not in tool_names: tool_result={"ok":False,"error":f"Unknown tool {name!r}."}
        elif name in {"remember_knowledge","recall_knowledge"}: tool_result=memory_call(name,args,knowledge)
        else:
            server=args.get("server"); command=command_for_tool(name,args)
            if server not in servers: tool_result={"ok":False,"error":f"Unknown server: {server!r}"}
            elif not command: tool_result={"ok":False,"error":f"Unsupported tool: {name!r}"}
            else:
                classification=policy.classify(command,name)
                if classification=="read_only" or policy.is_remembered(server,command,name):
                    tool_result=_execute(server,command,name)
                else:
                    pending_id=uuid.uuid4().hex; _pending[pending_id]={"session_id":sid,"server":server,"command":command,"tool_name":name,"args":args,"classification":classification}
                    return {"type":"approval","pending_id":pending_id,"tool":name,"server":server,"command":command,"classification":classification,"preview":args.get("content") if name=="write_file" else None,"step":step}
        messages.append({"role":"tool","content":json.dumps(compact_tool_result(tool_result),ensure_ascii=False)})
        if len(messages)>max_history: messages[:]=[messages[0]]+messages[-(max_history-1):]
    return {"type":"error","content":f"Stopped after {max_steps} agent steps. The task may be incomplete.","step":max_steps}

@app.get("/")
def index(): return send_from_directory(app.static_folder,"index.html")

@app.get("/api/config")
def api_config(): return jsonify({"model":ollama.model,"servers":list(servers),"memory_items":len(knowledge.entries)})

@app.post("/api/session")
def api_session():
    with _lock: sid=_new_session()
    return jsonify({"session_id":sid})

@app.post("/api/chat")
def api_chat():
    body=request.get_json(silent=True) or {}; sid=_session(body.get("session_id")); text=str(body.get("message","")).strip()
    if not text: return jsonify({"error":"Message is required."}),400
    try: return jsonify({"session_id":sid,**_run_turn(sid,text)})
    except Exception as exc: return jsonify({"session_id":sid,"type":"error","content":f"{type(exc).__name__}: {exc}"}),500

@app.post("/api/approval/<pending_id>")
def api_approval(pending_id):
    body=request.get_json(silent=True) or {}; decision=body.get("decision","deny"); remember=bool(body.get("remember",False))
    with _lock: pending=_pending.pop(pending_id,None)
    if not pending: return jsonify({"error":"Approval request expired or was already handled."}),404
    sid=pending["session_id"]
    if decision!="allow":
        _sessions[sid]["messages"].append({"role":"tool","content":json.dumps({"ok":False,"error":"User denied the proposed change."})})
        return jsonify({"session_id":sid,"type":"denied","content":"Change denied."})
    if pending["classification"]=="high_risk": remember=False
    if remember:
        approved=policy.approved.setdefault(pending["server"],[])
        if pending["command"] not in approved: approved.append(pending["command"]); policy._save()
    result=_execute(pending["server"],pending["command"],pending["tool_name"])
    try: continuation=_run_turn(sid,"",approved_pending=result)
    except Exception as exc: return jsonify({"session_id":sid,"type":"error","content":f"{type(exc).__name__}: {exc}","execution":result}),500
    return jsonify({"session_id":sid,**continuation,"execution":result})

if __name__=="__main__": app.run(host="0.0.0.0",port=8080,debug=False)
