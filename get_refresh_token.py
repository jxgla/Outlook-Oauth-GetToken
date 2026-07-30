"""
Outlook OAuth2 Token 批量获取工具（DrissionPage 版）

从 not_oauth2.txt 读取已注册但未授权的账号（每行：邮箱----密码），
逐个完成 OAuth2 授权，将 refresh_token 写入结果文件。
"""
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from controllers import dp_page as D
from controllers import oauth2 as OAUTH
from controllers.proxy_pool import LocalForwarder, ProxyPool

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
EXAMPLE_CONFIG_FILE = os.path.join(BASE_DIR, 'config.example.json')
RESULT_WRITE_LOCK = threading.Lock()
LOG_LOCK = threading.Lock()
_IP_INFO_CACHE = {}
_IP_INFO_LOCK = threading.Lock()

DEFAULT_WINDOW_SIZES = [(1366, 768), (1440, 900), (1536, 864), (1920, 1080)]


def _read_jsonc(path):
    with open(path, 'r', encoding='utf-8') as f:
        raw = f.read()
    lines = [line for line in raw.split('\n') if not line.strip().startswith('//')]
    return json.loads('\n'.join(lines))


def load_config():
    if os.path.exists(CONFIG_FILE):
        cfg = _read_jsonc(CONFIG_FILE)
    elif os.path.exists(EXAMPLE_CONFIG_FILE):
        cfg = _read_jsonc(EXAMPLE_CONFIG_FILE)
    else:
        cfg = {}

    cfg.setdefault('input_file', 'not_oauth2.txt')
    cfg.setdefault('output_file', os.path.join('Results', 'oauth2.txt'))
    cfg.setdefault('accounts_output_file', os.path.join('Results', 'accounts.txt'))
    cfg.setdefault('concurrent', 1)
    cfg.setdefault('headless', False)
    cfg.setdefault('log_dir', 'log')

    browser_cfg = cfg.get('browser') or {}
    browser_cfg.setdefault('path', '')
    browser_cfg.setdefault('window_size', None)
    browser_cfg.setdefault('background', False)
    browser_cfg.setdefault('block_images', False)
    cfg['browser'] = browser_cfg

    proxy_cfg = cfg.get('proxy') or {}
    proxy_cfg.setdefault('mode', 'single')
    proxy_cfg.setdefault('type', 'http')
    proxy_cfg.setdefault('host', '127.0.0.1')
    proxy_cfg.setdefault('single_port', 7890)
    proxy_cfg.setdefault('port_start', 24000)
    proxy_cfg.setdefault('port_end', 24005)
    proxy_cfg.setdefault('max_per_proxy', 20)
    proxy_cfg.setdefault('pool_type', 'socks5')
    proxy_cfg.setdefault('pool_file', 'proxypool.txt')
    proxy_cfg.setdefault('front_proxy', '')
    cfg['proxy'] = proxy_cfg

    oauth2_cfg = cfg.get('oauth2') or {}
    oauth2_cfg.setdefault('client_id', OAUTH.CLIENT_ID)
    oauth2_cfg.setdefault('redirect_url', OAUTH.REDIRECT_URI)
    oauth2_cfg.setdefault('tenant', 'common')
    oauth2_cfg.setdefault('Scopes', [
        'offline_access',
        'https://graph.microsoft.com/.default',
    ])
    oauth2_cfg.setdefault('rt_scope', 'graph')
    cfg['oauth2'] = oauth2_cfg

    temp_cfg = cfg.get('temp_mail') or {}
    temp_cfg.setdefault('enabled', False)
    temp_cfg.setdefault('provider', 'cloudflare')
    temp_cfg.setdefault('base_url', '')
    temp_cfg.setdefault('admin_password', '')
    temp_cfg.setdefault('domain', '')
    temp_cfg.setdefault('name_prefix', '')
    temp_cfg.setdefault('enable_prefix', False)
    temp_cfg.setdefault('code_timeout', 120)
    temp_cfg.setdefault('poll_interval', 3)
    temp_cfg.setdefault('timeout', 30)
    temp_cfg.setdefault('self', {
        'base_url': '',
        'api_key': '',
        'domain_mode': 'random',
        'domain': '',
        'name_prefix': '',
    })
    cfg['temp_mail'] = temp_cfg
    return cfg


def _abs_path(path_text):
    if not path_text:
        return ''
    if os.path.isabs(path_text):
        return path_text
    return os.path.join(BASE_DIR, path_text)


def resolve_paths(cfg):
    output_path = _abs_path(cfg.get('output_file') or os.path.join('Results', 'oauth2.txt'))
    accounts_output = _abs_path(
        cfg.get('accounts_output_file')
        or os.path.join(os.path.dirname(output_path), 'accounts.txt')
    )
    input_path = _abs_path(cfg.get('input_file') or 'not_oauth2.txt')
    log_dir = _abs_path(cfg.get('log_dir') or 'log')
    return {
        'input_path': input_path,
        'output_path': output_path,
        'accounts_output_path': accounts_output,
        'log_dir': log_dir,
    }


def load_accounts(path):
    if not os.path.exists(path):
        _safe_console_print(f"[Error] 未找到 {path}")
        return []
    accounts = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '----' in line:
                parts = line.split('----')
                if len(parts) >= 2:
                    accounts.append((parts[0].strip(), parts[1].strip()))
    return accounts


def _compact_exc(exc, max_len=220):
    text = str(exc) if exc is not None else ''
    if not text:
        return ''
    first = text.strip().splitlines()[0].strip()
    if len(first) > max_len:
        first = first[: max_len - 3] + '...'
    return first


def _get_ip_info(proxy_url, requests_proxy_url=None, timeout=5, use_cache=True):
    req_url = requests_proxy_url or proxy_url
    if not req_url:
        return {'country': '??', 'timezone': 'UTC', 'loc': None, 'ip': None}
    cache_key = proxy_url or requests_proxy_url
    if use_cache:
        with _IP_INFO_LOCK:
            if cache_key in _IP_INFO_CACHE:
                return _IP_INFO_CACHE[cache_key]
    info = {'country': '??', 'timezone': 'UTC', 'loc': None, 'ip': None}
    try:
        r = requests.get(
            'https://ipinfo.io/json',
            proxies={'http': req_url, 'https': req_url},
            timeout=timeout,
            headers={'Accept': 'application/json'},
        )
        if r.status_code == 200:
            d = r.json()
            info = {
                'country': d.get('country', '??'),
                'timezone': d.get('timezone', 'UTC'),
                'loc': d.get('loc'),
                'ip': d.get('ip'),
            }
    except Exception:
        pass
    if use_cache:
        with _IP_INFO_LOCK:
            _IP_INFO_CACHE[cache_key] = info
    return info


def _safe_console_print(text):
    line = str(text)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        try:
            import sys
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            safe = line.encode(enc, errors='replace').decode(enc, errors='replace')
        except Exception:
            safe = line.encode('ascii', errors='replace').decode('ascii', errors='replace')
        print(safe, flush=True)


class RunLogger:
    def __init__(self, log_dir):
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        self.oauth_debug_dir = os.path.join(self.log_dir, 'oauth_debug')
        os.makedirs(self.oauth_debug_dir, exist_ok=True)
        self.log_path = os.path.join(
            self.log_dir,
            f"{time.strftime('%Y-%m-%d_%H-%M-%S')}_{os.getpid()}.txt",
        )

    def write(self, text):
        line = str(text)
        with LOG_LOCK:
            _safe_console_print(line)
            with open(self.log_path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')

    def make_log_hook(self, tag, t0):
        def _hook(stage, message, level='INFO'):
            self.write(f"{tag}[{level}] {time.strftime('%H:%M:%S')} | +{time.time()-t0:.0f}s {stage} | {message}")
        return _hook

    def make_observer(self, tag):
        safe_tag = tag.strip('[]').replace('/', '_').replace(':', '-') or 'oauth'

        def _observer(stage, page=None):
            if not page:
                return
            stamp = time.strftime('%Y-%m-%d_%H-%M-%S')
            name = f"{stamp}_{safe_tag}_{stage}.png"
            try:
                page.get_screenshot(path=self.oauth_debug_dir, name=name)
                self.write(f"{tag}[WARN] {time.strftime('%H:%M:%S')} | {stage} | 已保存故障截图 {os.path.join(self.oauth_debug_dir, name)}")
            except Exception:
                pass
        return _observer


class ProxyManager:
    def __init__(self, cfg, logger):
        self.cfg = cfg or {}
        self.logger = logger
        self.mode = (self.cfg.get('mode') or 'single').strip().lower()
        self.type = self.cfg.get('type', 'http')
        self.host = self.cfg.get('host', '127.0.0.1')
        self.max_per = int(self.cfg.get('max_per_proxy', 20))
        self._usage = {}
        self._lock = threading.Lock()
        self._bad_ips = set()
        self._pool = None
        if self.mode == 'pool':
            pool_file = _abs_path(self.cfg.get('pool_file') or 'proxypool.txt')
            self._pool = ProxyPool(pool_file, default_type=self.cfg.get('pool_type', 'socks5'))
        elif self.mode == 'single':
            self.ports = [int(self.cfg.get('single_port', 7890))]
        else:
            start = int(self.cfg.get('port_start', 24000))
            end = int(self.cfg.get('port_end', 24005))
            self.ports = list(range(start, end + 1))

    def _pick_simple(self):
        with self._lock:
            available = [p for p in self.ports if self._usage.get(p, 0) < self.max_per]
            if not available:
                available = list(self.ports)
                for p in available:
                    self._usage[p] = 0
            port = random.choice(available)
            self._usage[port] = self._usage.get(port, 0) + 1
        proxy_url = f"{self.type}://{self.host}:{port}"
        info = _get_ip_info(proxy_url)
        return {
            'browser_proxy': proxy_url,
            'requests_proxy': proxy_url,
            'forwarder': None,
            'info': info,
            'exit_ip': info.get('ip'),
            'proxy_key': proxy_url,
        }

    def _pick_pool(self):
        if self._pool is None:
            return None
        front = self.cfg.get('front_proxy', '')
        max_attempts = max(self._pool.size() * 2, 8)
        for _ in range(max_attempts):
            entry = self._pool.next_entry()
            if entry is None:
                self.logger.write('[PROXY][FAIL] 代理池所有条目均不可用')
                return None
            try:
                fwd = LocalForwarder(entry, front_proxy=front)
            except Exception as exc:
                self._pool.mark_proxy_bad(entry['raw'])
                self.logger.write(f"[PROXY][WARN] 启动本地转发器失败，跳过 {entry['host']}:{entry['port']}: {_compact_exc(exc)}")
                continue
            test_url = f"socks5h://127.0.0.1:{fwd.port}"
            info = _get_ip_info(entry['raw'], requests_proxy_url=test_url, timeout=15, use_cache=False)
            exit_ip = info.get('ip')
            if not exit_ip:
                fwd.stop()
                self._pool.mark_proxy_bad(entry['raw'])
                self.logger.write(f"[PROXY][WARN] 连通性失败，记录并跳过 {entry['host']}:{entry['port']}")
                continue
            if exit_ip in self._bad_ips:
                fwd.stop()
                self.logger.write(f"[PROXY][INFO] 出口IP {exit_ip} 已被标记，跳过换下一条")
                continue
            self.logger.write(
                f"[PROXY][INFO] 顺序取 {entry['host']}:{entry['port']} → 本地端口 {fwd.port}"
                f"（{'经前置代理' if front else '直连'}），出口IP={exit_ip} 国家={info.get('country')}"
            )
            return {
                'browser_proxy': fwd.local_url,
                'requests_proxy': test_url,
                'forwarder': fwd,
                'info': info,
                'exit_ip': exit_ip,
                'proxy_key': entry['raw'],
                'upstream': entry['requests_url'],
            }
        self.logger.write(f"[PROXY][FAIL] 连续 {max_attempts} 次取代理均不可用")
        return None

    def pick(self):
        if self.mode == 'pool':
            return self._pick_pool()
        return self._pick_simple()

    def fresh_token_proxy(self, exclude='', current_ctx=None):
        if self.mode == 'pool':
            return (current_ctx or {}).get('requests_proxy', '')
        for _ in range(4):
            candidate = self._pick_simple()['requests_proxy']
            if not exclude or candidate != exclude:
                return candidate
        return self._pick_simple()['requests_proxy']

    def release(self, ctx):
        if not ctx:
            return
        fwd = ctx.get('forwarder')
        if fwd is not None:
            try:
                fwd.stop()
            except Exception:
                pass

    def mark_exit_ip_bad(self, ip):
        if ip:
            self._bad_ips.add(ip)
            if self._pool is not None:
                self._pool.mark_ip_bad(ip)



def _window_size_from_cfg(browser_cfg):
    ws = browser_cfg.get('window_size')
    if isinstance(ws, (list, tuple)) and len(ws) == 2:
        return int(ws[0]), int(ws[1])
    return random.choice(DEFAULT_WINDOW_SIZES)


def _launch_browser(ctx, cfg, logger, tag, t0):
    browser_cfg = cfg.get('browser') or {}
    proxy_url = ctx.get('browser_proxy') or ''
    requests_proxy = ctx.get('requests_proxy') or proxy_url
    info = ctx.get('info') or _get_ip_info(proxy_url, requests_proxy_url=requests_proxy)
    timezone = info.get('timezone') if info and info.get('timezone') and info.get('timezone') != 'UTC' else None
    loc = info.get('loc') if info else None
    window_size = _window_size_from_cfg(browser_cfg)
    extra_args = ['--blink-settings=imagesEnabled=false'] if browser_cfg.get('block_images') else None
    browser, tab = D.build_browser(
        proxy_url=proxy_url,
        headless=bool(cfg.get('headless', False)),
        window_size=window_size,
        browser_path=(browser_cfg.get('path') or '').strip() or None,
        extra_args=extra_args,
    )
    D.prepare_tab(tab, timezone=timezone, locale='zh-CN', loc=loc)
    if browser_cfg.get('background') and not cfg.get('headless', False):
        try:
            D.minimize_window(tab)
        except Exception:
            pass
    logger.write(
        f"{tag}[INFO] {time.strftime('%H:%M:%S')} | +{time.time()-t0:.0f}s launch | "
        f"exe=system-chrome tz={timezone or 'UTC'} win={window_size[0]}x{window_size[1]} proxy={proxy_url.split('//')[-1]}"
    )
    return browser, tab


def append_oauth_result(paths, email, password, client_id, refresh_token, aux_email=''):
    os.makedirs(os.path.dirname(paths['output_path']), exist_ok=True)
    with RESULT_WRITE_LOCK:
        with open(paths['output_path'], 'a', encoding='utf-8') as f:
            f.write(f"{email}----{password}----{client_id}----{refresh_token}----{aux_email or ''}\n")
        with open(paths['accounts_output_path'], 'a', encoding='utf-8') as f:
            f.write(f"{email}----{password}----{client_id}----{refresh_token}\n")


def process_single_account(email, password, proxy_manager, cfg, logger, idx, total):
    t0 = time.time()
    tag = f"[{idx}/{total}]"
    logger.write(f"{tag} {time.strftime('%H:%M:%S')} | 开始: {email}")

    ctx = proxy_manager.pick()
    if not ctx:
        return email, False, '无可用代理', ''

    browser = None
    page = None
    recovery_session = None
    try:
        browser, page = _launch_browser(ctx, cfg, logger, tag, t0)
        ok, refresh_token, recovery_session = OAUTH.get_oauth2_token_cold(
            page,
            email,
            password,
            prefix=tag,
            log_hook=logger.make_log_hook(tag, t0),
            observer=logger.make_observer(tag),
            current_proxy=ctx.get('requests_proxy') or ctx.get('browser_proxy') or '',
            token_proxy_getter=lambda exclude='': proxy_manager.fresh_token_proxy(exclude=exclude, current_ctx=ctx),
            temp_mail_cfg=cfg.get('temp_mail') or {},
            recovery_already_bound=False,
            recovery_session=recovery_session,
        )
        if not ok:
            return email, False, 'OAuth2失败', (recovery_session or {}).get('address', '')
        return email, True, refresh_token, (recovery_session or {}).get('address', '')
    except Exception as exc:
        return email, False, _compact_exc(exc) or '运行异常', (recovery_session or {}).get('address', '')
    finally:
        try:
            if browser is not None:
                browser.quit(timeout=5, force=True, del_data=True)
        except Exception:
            pass
        proxy_manager.release(ctx)


def _ensure_runtime_inputs(paths):
    created = []
    if not os.path.exists(paths['input_path']):
        example = os.path.join(BASE_DIR, 'not_oauth2.example.txt')
        if os.path.exists(example):
            with open(example, 'r', encoding='utf-8') as src, open(paths['input_path'], 'w', encoding='utf-8') as dst:
                dst.write(src.read())
        else:
            with open(paths['input_path'], 'w', encoding='utf-8') as dst:
                dst.write('# 邮箱----密码\n')
        created.append(paths['input_path'])
    return created


def main():
    cfg = load_config()
    paths = resolve_paths(cfg)
    created = _ensure_runtime_inputs(paths)
    accounts = load_accounts(paths['input_path'])
    if not accounts:
        if created:
            _safe_console_print(f"[Init] 已创建示例输入文件: {', '.join(created)}")
        _safe_console_print(f"没有待处理的账号。请在 {paths['input_path']} 中添加（格式：邮箱----密码）")
        return

    logger = RunLogger(paths['log_dir'])
    applied = OAUTH.configure_oauth2(cfg.get('oauth2'))
    proxy_manager = ProxyManager(cfg.get('proxy') or {}, logger)
    total = len(accounts)
    concurrent = min(int(cfg.get('concurrent', 1)), total)

    logger.write(
        f"[OAuth] client_id={applied['client_id']} tenant={applied['tenant']} redirect_uri={applied['redirect_uri']} "
        f"auth_scope={applied['auth_scope']} token_scope={applied['token_scope']} rt_scope={applied['rt_scope']}"
    )
    logger.write(f"[Log] 本次日志文件: {logger.log_path}")
    logger.write(f"[Cfg] concurrent={concurrent} headless={bool(cfg.get('headless', False))} proxy_mode={(cfg.get('proxy') or {}).get('mode', 'single')}")
    logger.write(f"共 {total} 个账号，{concurrent} 并发")
    logger.write('')

    succeeded = []
    failed = []
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=concurrent) as executor:
        futures = {
            executor.submit(process_single_account, email, password, proxy_manager, cfg, logger, i, total): (email, password, i)
            for i, (email, password) in enumerate(accounts, 1)
        }
        for future in as_completed(futures):
            email, password, _idx = futures[future]
            email, success, result, aux_email = future.result()
            if success:
                append_oauth_result(paths, email, password, applied['client_id'], result, aux_email)
                succeeded.append((email, result))
                logger.write(f"[结果] OK  {email}")
            else:
                failed.append((email, result))
                logger.write(f"[结果] FAIL {email} | 原因={result}")
            done = len(succeeded) + len(failed)
            logger.write(
                f"[进度] {done}/{total} 成功{len(succeeded)} 失败{len(failed)} | "
                f"耗时 {((time.time()-t_start)/60):.1f}min"
            )

    logger.write('\n=== 完成 ===')
    logger.write(f"成功: {len(succeeded)}/{total}")
    logger.write(f"失败: {len(failed)}/{total}")
    logger.write(f"耗时: {(time.time()-t_start)/60:.1f}min")
    if failed:
        logger.write('失败明细：')
        for email, reason in failed:
            logger.write(f"- {email} | {reason}")
    logger.write(f"[Log] 已写入: {logger.log_path}")


if __name__ == '__main__':
    main()
