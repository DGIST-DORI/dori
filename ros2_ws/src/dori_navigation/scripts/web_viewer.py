#!/usr/bin/env python3
"""Serve the robot viewer locally; no hardware startup or motor output."""
import argparse
from pathlib import Path
import sys
import threading
import os
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rclpy
from dori_web.bridge import WebBridge
from dori_web.http_server import ViewerServer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--user-port',type=int,default=None,help='User port; defaults to 7070 with admin port 8080, 0 disables it')
    parser.add_argument('--user-host',default=None,help='User backend bind address; defaults to loopback when a voice HTTPS URL is configured')
    parser.add_argument('--goals-file',default=None)
    parser.add_argument('--voice-url',default=None,help='HTTPS URL advertised for remote microphone access')
    parser.add_argument('--mode', choices=['auto', 'monitor', 'mapping', 'navigation'], default='auto')
    args, ros_args = parser.parse_known_args()
    url_file=Path.home()/'.config/dori/user_https_url'
    if args.voice_url:os.environ['DORI_USER_HTTPS_URL']=args.voice_url
    elif url_file.exists():os.environ.setdefault('DORI_USER_HTTPS_URL',url_file.read_text().strip())
    user_host=args.user_host or ('127.0.0.1' if os.getenv('DORI_USER_HTTPS_URL') else args.host)
    rclpy.init(args=ros_args)
    node = WebBridge(args.mode,args.goals_file)
    server = ViewerServer((args.host, args.port), node)
    servers=[server]
    user_port=args.user_port if args.user_port is not None else (7070 if args.port==8080 else 0)
    if user_port:servers.append(ViewerServer((user_host,user_port),node,role='user'))
    workers=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
    for worker in workers:worker.start()
    print(f'Dori viewer: http://{args.host}:{server.server_port} ({args.mode})', flush=True)
    if user_port:
        print(f'Dori user backend: http://{user_host}:{user_port}',flush=True)
        if os.getenv('DORI_USER_HTTPS_URL'):print(f'Dori user page: {os.environ["DORI_USER_HTTPS_URL"]}',flush=True)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.owner and rclpy.ok():
            node.stop()
        for server in servers:server.shutdown();server.server_close()
        for worker in workers:worker.join(timeout=2)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
