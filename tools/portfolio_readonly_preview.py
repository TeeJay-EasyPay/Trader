"""Local emulator preview: production GETs only; new charts use a read-only DB.

Never run the trading API/worker locally for UI preview. No POST route is exposed.
Bind loopback; use adb reverse for the emulator. Credentials never enter responses.
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from ai_trader.config import load_dotenv

load_dotenv()
os.environ['DATABASE_URL'] = os.environ['AUDIT_DATABASE_URL']
os.environ['AI_TRADER_DATABASE_BACKEND'] = 'postgres'
os.environ['PGOPTIONS'] = '-c default_transaction_read_only=on -c statement_timeout=20000'

from ai_trader.portfolio_trends import portfolio_trends


class Preview(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == '/portfolio-trends':
                payload = json.dumps(portfolio_trends('preview'), allow_nan=False).encode()
            else:
                request = Request('https://trader-no0f.onrender.com' + self.path,
                                  headers={'Authorization': 'Bearer ' + os.environ['AI_TRADER_API_TOKEN']})
                with urlopen(request, timeout=45) as response:
                    payload = response.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except HTTPError as exc:
            self.send_error(exc.code)
        except Exception:
            self.send_error(502, 'Read-only preview unavailable')

    def do_POST(self):
        self.send_error(405, 'Trading and all writes are disabled in this preview')

    def log_message(self, *_):
        pass


if __name__ == '__main__':
    print('Read-only portfolio preview on 127.0.0.1:8089', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8089), Preview).serve_forever()
