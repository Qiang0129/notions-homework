"""Single-instance production entry point. No test transport or plaintext SMTP option."""
from __future__ import annotations
import argparse
import socket
import sys
import threading
import webbrowser
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import uvicorn

def main():
    parser=argparse.ArgumentParser(description='课信 · 本地作业邮件提醒助手')
    parser.add_argument('--lan',action='store_true',help='监听所有本地接口，仅供可信私人网络访问')
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--open-browser',action='store_true')
    args=parser.parse_args()
    if not 1<=args.port<=65535: parser.error('端口必须为 1–65535')
    host='0.0.0.0' if args.lan else '127.0.0.1'
    try:
        with socket.socket() as sock: sock.bind((host,args.port))
    except OSError:
        print(f'无法监听端口 {args.port}：端口已占用或无权限。请通过 -Port 指定其他端口。',file=sys.stderr); return 1
    print(f'\n课信 · http://127.0.0.1:{args.port}\n首次请从电脑本机打开并设置管理员密码。\n按 Ctrl+C 停止服务；停止后不会继续发送邮件。\n',flush=True)
    if args.lan:
        print('警告：局域网使用 HTTP，网页传输不加密。请勿公网映射，不会自动修改防火墙。',flush=True)
        try:
            addresses={row[4][0] for row in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET)}
            for addr in sorted(addresses):
                if not addr.startswith(('127.','169.254.')): print(f'候选局域网地址：http://{addr}:{args.port}（请选择当前私人网络网卡）',flush=True)
        except OSError: pass
    if args.open_browser:
        threading.Timer(1.8,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    uvicorn.run('app.main:app',host=host,port=args.port,workers=1,proxy_headers=False,access_log=False,log_level='info')
    return 0

if __name__=='__main__': raise SystemExit(main())
