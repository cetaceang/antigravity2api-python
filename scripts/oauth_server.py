#!/usr/bin/env python3
import http.server
import urllib.parse
import urllib.request
import json
import uuid
import os
import random
import string
from datetime import datetime
import webbrowser
import threading

CLIENT_ID = '1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com'
CLIENT_SECRET = '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'
STATE = str(uuid.uuid4())

SCOPES = [
    'https://www.googleapis.com/auth/cloud-platform',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'https://www.googleapis.com/auth/cclog',
    'https://www.googleapis.com/auth/experimentsandconfigs'
]

def generate_project_id():
    """生成随机 project_id，格式: adjective-noun-random5"""
    adjectives = ['useful', 'bright', 'swift', 'calm', 'bold']
    nouns = ['fuze', 'wave', 'spark', 'flow', 'core']
    random_adj = random.choice(adjectives)
    random_noun = random.choice(nouns)
    random_chars = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f'{random_adj}-{random_noun}-{random_chars}'

# ANSI 颜色代码
COLORS = {
    'reset': '\033[0m',
    'green': '\033[32m',
    'yellow': '\033[33m',
    'red': '\033[31m',
    'gray': '\033[90m'
}

def log_info(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"{COLORS['gray']}{timestamp}{COLORS['reset']} {COLORS['green']}[info]{COLORS['reset']} {msg}")

def log_warn(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"{COLORS['gray']}{timestamp}{COLORS['reset']} {COLORS['yellow']}[warn]{COLORS['reset']} {msg}")

def log_error(msg):
    timestamp = datetime.now().strftime('%H:%M:%S')
    print(f"{COLORS['gray']}{timestamp}{COLORS['reset']} {COLORS['red']}[error]{COLORS['reset']} {msg}")

def generate_auth_url(port):
    params = {
        'access_type': 'offline',
        'client_id': CLIENT_ID,
        'prompt': 'consent',
        'redirect_uri': f'http://localhost:{port}/oauth-callback',
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'state': STATE
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

def exchange_code_for_token(code, port):
    data = {
        'code': code,
        'client_id': CLIENT_ID,
        'redirect_uri': f'http://localhost:{port}/oauth-callback',
        'grant_type': 'authorization_code'
    }

    if CLIENT_SECRET:
        data['client_secret'] = CLIENT_SECRET

    encoded_data = urllib.parse.urlencode(data).encode('utf-8')

    req = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=encoded_data,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        raise Exception(f"HTTP {e.code}: {error_body}")

class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 禁用默认日志

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == '/oauth-callback':
            query_params = urllib.parse.parse_qs(parsed_url.query)
            code = query_params.get('code', [None])[0]
            error = query_params.get('error', [None])[0]

            if code:
                log_info('收到授权码，正在交换 Token...')
                try:
                    port = self.server.server_port
                    token_data = exchange_code_for_token(code, port)

                    # 计算过期时间戳
                    expires_at = int(datetime.now().timestamp()) + token_data['expires_in']

                    # 生成新的项目配置
                    new_project = {
                        'project_id': generate_project_id(),
                        'refresh_token': token_data.get('refresh_token'),
                        'access_token': token_data['access_token'],
                        'expires_at': expires_at,
                        'enabled': True,
                        'disabled_reason': None
                    }

                    # 读取现有配置
                    tokens_file = 'data/tokens.json'
                    if os.path.exists(tokens_file):
                        try:
                            with open(tokens_file, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                        except Exception:
                            log_warn('读取 data/tokens.json 失败，将创建新文件')
                            data = {
                                'oauth_config': {
                                    'client_id': CLIENT_ID,
                                    'client_secret': CLIENT_SECRET,
                                    'token_url': 'https://oauth2.googleapis.com/token'
                                },
                                'projects': []
                            }
                    else:
                        # 创建目录和初始结构
                        os.makedirs('data', exist_ok=True)
                        data = {
                            'oauth_config': {
                                'client_id': CLIENT_ID,
                                'client_secret': CLIENT_SECRET,
                                'token_url': 'https://oauth2.googleapis.com/token'
                            },
                            'projects': []
                        }

                    # 添加新项目到 projects 数组
                    if 'projects' not in data:
                        data['projects'] = []
                    data['projects'].append(new_project)

                    # 保存回文件
                    with open(tokens_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)

                    log_info(f'Token 已保存到 data/tokens.json，project_id: {new_project["project_id"]}')

                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write('<h1>授权成功！</h1><p>Token 已保存，可以关闭此页面。</p>'.encode('utf-8'))

                    threading.Timer(1.0, self.server.shutdown).start()

                except Exception as e:
                    log_error(f'Token 交换失败: {str(e)}')

                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write('<h1>Token 获取失败</h1><p>查看控制台错误信息</p>'.encode('utf-8'))

                    threading.Timer(1.0, self.server.shutdown).start()
            else:
                log_error(f'授权失败: {error or "未收到授权码"}')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write('<h1>授权失败</h1>'.encode('utf-8'))
                threading.Timer(1.0, self.server.shutdown).start()
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not Found')

def main():
    server = http.server.HTTPServer(('localhost', 0), OAuthHandler)
    port = server.server_port
    auth_url = generate_auth_url(port)

    log_info(f'服务器运行在 http://localhost:{port}')
    log_info('请在浏览器中打开以下链接进行登录：')
    print(f'\n{auth_url}\n')
    log_info('等待授权回调...')

    server.serve_forever()

if __name__ == '__main__':
    main()
