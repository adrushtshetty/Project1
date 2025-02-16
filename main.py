from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
import os
import subprocess
import base64
import requests
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import ast

app = FastAPI()

DATA_DIR = "/data"

def read_data_file(path: str) -> str:
    full_path = os.path.abspath(os.path.join(DATA_DIR, path))
    if not full_path.startswith(DATA_DIR):
        raise HTTPException(status_code=400, detail="Access outside /data is not allowed")
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(full_path, "r") as f:
        return f.read()

def write_data_file(path: str, content: str):
    full_path = os.path.abspath(os.path.join(DATA_DIR, path))
    if not full_path.startswith(DATA_DIR):
        raise HTTPException(status_code=400, detail="Access outside /data is not allowed")
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w") as f:
        f.write(content)

def run_command(command: str):
    if any(cmd in command for cmd in ["rm", "del", "unlink"]):
        raise HTTPException(status_code=400, detail="Deleting files is not allowed")
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            cwd=DATA_DIR
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=400, detail=f"Command failed: {e.stderr}")

def llm_query(prompt: str, image_path: str = None) -> str:
    api_url = "https://api.aiproxy.io/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.environ['AIPROXY_TOKEN']}",
        "Content-Type": "application/json"
    }
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    if image_path:
        full_path = os.path.join(DATA_DIR, image_path)
        with open(full_path, "rb") as img_file:
            base64_image = base64.b64encode(img_file.read()).decode("utf-8")
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{base64_image}"}
        })
    data = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "max_tokens": 300
    }
    response = requests.post(api_url, json=data, headers=headers)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def parse_task(task: str) -> str:
    prompt = f"""
    You are an automation agent. Given the task: {task}, generate Python code using the functions:
    - read_data_file(path) to read files under /data
    - write_data_file(path, content) to write files under /data
    - run_command(command) to execute allowed shell commands
    Do not delete files or access outside /data. Return only valid Python code.
    """
    return llm_query(prompt)

@app.post("/run")
async def run_task(task: str = Query(...)):
    try:
        code = parse_task(task)
        env = {
            "read_data_file": read_data_file,
            "write_data_file": write_data_file,
            "run_command": run_command,
            "__builtins__": {},
            "llm_query": llm_query
        }
        exec(code, env)
        return {"status": "success"}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/read")
async def read_file(path: str = Query(...)):
    try:
        content = read_data_file(path)
        return content
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
