"""Runs inside network-isolated sandbox; relays only to the host budget socket."""
import os
import shutil
import http.client
import http.server
import socket
import subprocess
import sys
import threading

class Connection(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.connect('/gateway.sock')

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def forward(self):
        n=int(self.headers.get('Content-Length','0'));body=self.rfile.read(n) if n else None
        c=Connection('localhost',timeout=180)
        c.request(self.command,self.path,body,dict(self.headers));r=c.getresponse();data=r.read()
        self.send_response(r.status)
        self.send_header('Content-Type',r.getheader('Content-Type','application/json'))
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);c.close()
    do_GET=forward
    do_POST=forward

os.makedirs('/tmp/qwen_home',exist_ok=True)
shutil.copyfile('/settings.json','/tmp/qwen_home/settings.json')
server=http.server.ThreadingHTTPServer(('127.0.0.1',8001),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
try:
    with open('/prompt.txt') as prompt:sys.exit(subprocess.call(sys.argv[1:],stdin=prompt))
finally:server.shutdown()
