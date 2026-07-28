import time
from urllib.parse import parse_qs, quote, urlparse

import requests
from DrissionPage.common import Keys

from controllers import dp_page as D

# === OAuth2 常量（默认值，可被 config['oauth2'] 覆盖，见 configure_oauth2）===
CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
REDIRECT_URI = "http://localhost"
AUTH_SCOPE = "offline_access https://graph.microsoft.com/.default"
TOKEN_SCOPE = AUTH_SCOPE
RT_SCOPE = "graph"
AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

CONSENT_SELECTOR = '[data-testid="appConsentPrimaryButton"]'
EMAIL_SELECTOR = "#i0116"
EMAIL_NEXT_SELECTOR = "#idSIButton9"
MSA_TILE_SELECTOR = "#msaTile"
MSA_TILE_TITLE_SELECTOR = "#msaTileTitle"
PASSWORD_BYPASS_TEXTS = [
    "使用密码",
    "使用密码登录",
    "Use password instead",
    "Use your password",
    "Sign in with a password",
]
PASSKEY_ALT_METHOD_TEXTS = [
    "换一种方式",
    "尝试其他方式",
    "其他方式",
    "Try another way",
    "Other ways to sign in",
    "Sign-in options",
]
PASSKEY_LOGIN_HINT_TEXTS = [
    "使用通行密钥登录",
    "用通行密钥登录",
    "passkey",
    "Passkey",
    "Windows Hello",
    "安全密钥",
    "security key",
]
PASSWORD_WRONG_TEXTS = [
    "此密码不是你的 Microsoft 帐户的正确密码",
    "This password is incorrect",
    "你的帐户或密码不正确",
    "帐户或密码不正确",
    "账户或密码不正确",
    "Your account or password is incorrect",
    "incorrect account or password",
]
PASSWORD_BLOCKED_TEXTS = [
    "密码登录不可用",
    "请尝试其他方法",
    "Password login is not available",
    "Try another way",
    "Try a different way",
    "Sign-in method isn't available",
]
ACCOUNT_TYPE_HINT_TEXTS = [
    "哪种类型的帐户",
    "哪种类型的账户",
    "which type of account",
    "Work or school account",
    "工作或学校帐户",
    "工作或学校账户",
    "个人帐户",
    "个人账户",
    "Personal account",
]
LOGIN_EMAIL_HINT_TEXTS = [
    "登录",
    "sign in",
    "使用你的 microsoft 帐户",
    "use your microsoft account",
    "电子邮件地址、电话或 skype",
    "电子邮件地址或电话号码",
    "电子邮件、电话或 skype",
    "email, phone, or skype",
    "email address, phone, or skype",
    "输入电子邮件",
    "enter email",
]
AUTH_NAV_TIMEOUT_MS = 45000
AUTH_ENTRY_TIMEOUT_MS = 45000


def configure_oauth2(cfg):
    """用 config['oauth2'] 覆盖 OAuth 常量，并拆分 auth/token scope。"""
    global CLIENT_ID, REDIRECT_URI, AUTH_SCOPE, TOKEN_SCOPE, RT_SCOPE, AUTHORIZE_URL, TOKEN_URL
    cfg = cfg or {}

    cid = str(cfg.get('client_id') or '').strip()
    if cid:
        CLIENT_ID = cid

    ru = str(cfg.get('redirect_url') or cfg.get('redirect_uri') or '').strip()
    if ru:
        REDIRECT_URI = ru

    scopes = cfg.get('Scopes') or cfg.get('scopes')
    auth_scope = AUTH_SCOPE
    if isinstance(scopes, (list, tuple)):
        joined = ' '.join(str(s).strip() for s in scopes if str(s).strip())
        if joined:
            auth_scope = joined
    elif isinstance(scopes, str) and scopes.strip():
        auth_scope = scopes.strip()
    AUTH_SCOPE = auth_scope

    graph_scopes = []
    imap_scopes = []
    common_scopes = []
    for item in AUTH_SCOPE.split():
        low = item.lower()
        if 'graph.microsoft.com/' in low:
            graph_scopes.append(item)
        elif 'outlook.office.com/' in low:
            imap_scopes.append(item)
        else:
            common_scopes.append(item)

    rt_scope = str(cfg.get('rt_scope') or cfg.get('RTScope') or cfg.get('rtScope') or 'graph').strip().lower()
    if rt_scope not in ('graph', 'imap'):
        rt_scope = 'graph'
    RT_SCOPE = rt_scope

    selected = imap_scopes if rt_scope == 'imap' else graph_scopes
    token_parts = common_scopes + selected
    TOKEN_SCOPE = ' '.join(part for part in token_parts if part).strip() or AUTH_SCOPE

    tenant = str(cfg.get('tenant') or cfg.get('authority') or '').strip().strip('/')
    if tenant:
        AUTHORIZE_URL = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        TOKEN_URL = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    return {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'auth_scope': AUTH_SCOPE,
        'token_scope': TOKEN_SCOPE,
        'rt_scope': RT_SCOPE,
        'tenant': tenant or 'common',
        'authorize_url': AUTHORIZE_URL,
    }


def build_auth_url(login_hint=''):
    params = {
        'client_id': CLIENT_ID,
        'response_type': 'code',
        'redirect_uri': REDIRECT_URI,
        'scope': AUTH_SCOPE,
        'prompt': 'login',
    }
    hint = str(login_hint or '').strip()
    if hint:
        params['login_hint'] = hint
    return f"{AUTHORIZE_URL}?{'&'.join(f'{k}={quote(v)}' for k, v in params.items())}"


def _extract_code_from_url(url):
    if not url or 'code=' not in url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    host = (parsed.hostname or '').lower()
    expected = (urlparse(REDIRECT_URI).hostname or '').lower()
    if host not in {'localhost', '127.0.0.1'} and host != expected:
        return None
    code = parse_qs(parsed.query).get('code', [None])[0]
    if code:
        return code
    if parsed.fragment and 'code=' in parsed.fragment:
        return parse_qs(parsed.fragment).get('code', [None])[0]
    return None


def _wait_for_code_capture(page, captured_code, timeout_ms=180000, poll_ms=250):
    def _scan():
        if captured_code and captured_code[0]:
            return captured_code[0]
        for getter in (lambda: page.url, lambda: page.run_js('return location.href')):
            try:
                code = _extract_code_from_url(getter())
            except Exception:
                code = None
            if code:
                if captured_code is not None:
                    captured_code[0] = code
                return code
        try:
            pkt = page.listen.wait(timeout=0.05, raise_err=False)
            if pkt:
                code = _extract_code_from_url(getattr(pkt, 'url', ''))
                if code:
                    if captured_code is not None:
                        captured_code[0] = code
                    return code
        except Exception:
            pass
        return None

    got = _scan()
    if got:
        return got
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        got = _scan()
        if got:
            return got
        try:
            page.wait(poll_ms / 1000.0)
        except Exception:
            time.sleep(poll_ms / 1000.0)
    return None


def _compact_exc(exc, max_len=180):
    text = str(exc) if exc is not None else ""
    if not text:
        return ""
    first = text.strip().splitlines()[0].strip()
    for marker in ("Call log:", "\nCall log"):
        idx = text.find(marker)
        if idx >= 0:
            first = text[:idx].strip().splitlines()[0].strip()
            break
    if len(first) > max_len:
        first = first[: max_len - 3] + "..."
    return first


def _wait_for_auth_state_or_code(page, captured_code, timeout_ms=AUTH_ENTRY_TIMEOUT_MS, poll_ms=500, ignore_states=None):
    ignore_states = set(ignore_states or ())
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        if captured_code and _wait_for_code_capture(page, captured_code, timeout_ms=0):
            return 'code'
        state = _current_auth_entry_state(page)
        if state != 'unknown' and state not in ignore_states:
            return state
        page.wait(poll_ms / 1000)
    if captured_code and _wait_for_code_capture(page, captured_code, timeout_ms=0):
        return 'code'
    state = _current_auth_entry_state(page)
    if state != 'unknown' and state not in ignore_states:
        return state
    return 'unknown'


def _wait_for_auth_entry_state(page, timeout_ms=AUTH_ENTRY_TIMEOUT_MS, poll_ms=500, ignore_states=None):
    return _wait_for_auth_state_or_code(page, None, timeout_ms=timeout_ms, poll_ms=poll_ms, ignore_states=ignore_states)


def _vis(page, sel):
    return D.vis(page, sel)


def _text_exists(page, text):
    return D.text_exists(page, text)


def _password_input_meta(item):
    try:
        visible = item.states.is_displayed
    except Exception:
        visible = False
    try:
        meta = item.run_js(
            """function() {
                const el = this;
                const cls = (el.className && el.className.toString) ? el.className.toString() : '';
                return {
                    id: el.id || '',
                    name: el.name || '',
                    type: el.getAttribute('type') || '',
                    tabindex: el.getAttribute('tabindex') || '',
                    ariaHidden: el.getAttribute('aria-hidden') || '',
                    readonly: el.hasAttribute('readonly'),
                    disabled: !!el.disabled,
                    cls,
                    off: !!(el.classList && el.classList.contains('moveOffScreen')),
                    hidden: !!(el.hidden || el.getAttribute('aria-hidden') === 'true'),
                    width: el.offsetWidth || 0,
                    height: el.offsetHeight || 0,
                };
            }"""
        ) or {}
    except Exception:
        meta = {}
    meta['visible'] = bool(visible)
    return meta


def _is_usable_password_input(item):
    meta = _password_input_meta(item)
    if not meta.get('visible'):
        return False
    if meta.get('hidden') or meta.get('disabled'):
        return False
    cls = str(meta.get('cls') or '').lower()
    if meta.get('off') or 'moveoffscreen' in cls or 'move-off-screen' in cls:
        return False
    if str(meta.get('ariaHidden') or '').lower() == 'true':
        return False
    width = int(meta.get('width') or 0)
    height = int(meta.get('height') or 0)
    if width < 4 or height < 4:
        return False
    if str(meta.get('tabindex')) == '-1' and width < 20:
        return False
    return True


def _password_input(page):
    selectors = (
        '#passwordEntry',
        'input[name="passwd"]',
        'input[type="password"]',
        '#i0118',
    )
    for sel in selectors:
        try:
            for item in D.q_all(page, sel):
                if _is_usable_password_input(item):
                    return item
        except Exception:
            pass
    for name in ("密码", "Password", "password"):
        try:
            el = D.q(page, f'xpath://input[@type="password" and (@aria-label="{name}" or @placeholder="{name}" or @name="{name}")]')
            if el and _is_usable_password_input(el):
                return el
        except Exception:
            pass
    return None


def _is_account_type_page(page):
    if _vis(page, MSA_TILE_SELECTOR) or _vis(page, MSA_TILE_TITLE_SELECTOR):
        return True
    has_personal = _text_exists(page, "个人帐户") or _text_exists(page, "个人账户") or _text_exists(page, "Personal account")
    has_work = _text_exists(page, "工作或学校帐户") or _text_exists(page, "工作或学校账户") or _text_exists(page, "Work or school account")
    if has_personal and has_work:
        return True
    for t in ACCOUNT_TYPE_HINT_TEXTS:
        if ("哪种类型" in t or "which type" in t.lower()) and _text_exists(page, t):
            return True
    return False


def _is_protect_account_page(page):
    try:
        from controllers.recovery_bind import is_protect_account_page, is_ott_code_page
        return is_protect_account_page(page) or is_ott_code_page(page)
    except Exception:
        if _vis(page, "#EmailAddress") or _vis(page, "#iOttText"):
            return True
        return _text_exists(page, "保护你的帐户") or _text_exists(page, "保护您的帐户")


def _is_proof_verify_page(page):
    try:
        from controllers.recovery_bind import is_proof_confirm_page, is_code_entry_page
        return is_proof_confirm_page(page) or is_code_entry_page(page)
    except Exception:
        if _vis(page, "#proof-confirmation-email-input") or _vis(page, "#codeEntry-0"):
            return True
        return _text_exists(page, "验证你的电子邮件") or _text_exists(page, "输入你的代码")


def _is_kmsi_only_page(page):
    try:
        from controllers.recovery_bind import is_kmsi_page, is_proof_confirm_page, is_code_entry_page
        return is_kmsi_page(page) and not is_proof_confirm_page(page) and not is_code_entry_page(page)
    except Exception:
        return _text_exists(page, "保持登录") or _text_exists(page, "Stay signed in")


def _is_login_email_page_loose(page):
    if _vis(page, EMAIL_SELECTOR):
        return True
    try:
        body = (D.body_text(page, limit=900) or "").strip()
    except Exception:
        body = ""
    body_l = body.lower()
    hint = any(t in body for t in LOGIN_EMAIL_HINT_TEXTS if any('一' <= c <= '鿿' for c in t))
    hint = hint or any(t in body_l for t in LOGIN_EMAIL_HINT_TEXTS if not any('一' <= c <= '鿿' for c in t))
    if not hint:
        return False
    if _vis(page, EMAIL_NEXT_SELECTOR):
        return True
    try:
        btn = D.role_button(page, '下一步', timeout=0)
        if btn and D._displayed(btn):
            return True
    except Exception:
        pass
    return _text_exists(page, '下一步') or _text_exists(page, 'Next')


def _is_passkey_login_prompt(page):
    try:
        url = page.url or ''
    except Exception:
        url = ''
    body = ''
    try:
        body = D.body_text(page, limit=1000) or ''
    except Exception:
        pass
    body_l = body.lower()
    if 'fido' in url:
        return True
    for text in PASSKEY_LOGIN_HINT_TEXTS:
        if any('一' <= c <= '鿿' for c in text):
            if text in body:
                return True
        elif text.lower() in body_l:
            return True
    return False


def _click_use_password(page):
    for text in PASSWORD_BYPASS_TEXTS:
        try:
            if D.click_role_button(page, text, timeout=0):
                page.wait(1.0)
                return True
        except Exception:
            pass
        try:
            if D.click_if_visible(page, f'text:{text}'):
                page.wait(1.0)
                return True
        except Exception:
            pass
        try:
            if D.click_if_visible(page, f'input[type="button"][value="{text}"]'):
                page.wait(1.0)
                return True
        except Exception:
            pass
    for sel in ('#iShowSkip', '#idA_PWD_SwitchToPassword', '#idA_PWD_SwitchToCredPicker'):
        try:
            if _vis(page, sel) and D.click_sel(page, sel, timeout=1.5):
                page.wait(1.0)
                return True
        except Exception:
            pass
    return False


def _dismiss_passkey_login_prompt(page, log=None):
    if not _is_passkey_login_prompt(page):
        return False
    if log:
        try:
            log('passkey', '检测到通行密钥登录提示，尝试切到密码登录', 'WARN')
        except Exception:
            pass
    try:
        if D.click_if_visible(page, 'text:使用另一种方式登录') or D.click_role_button(page, '使用另一种方式登录', timeout=0):
            page.wait(1.0)
    except Exception:
        pass
    if _click_use_password(page):
        if log:
            try:
                log('passkey', '已切换到密码登录', 'OK')
            except Exception:
                pass
        return True
    if _click_alt_signin_method(page) and _click_use_password(page):
        if log:
            try:
                log('passkey', '已通过其他登录方式切到密码登录', 'OK')
            except Exception:
                pass
        return True
    return False


def _current_auth_entry_state(page):
    if _vis(page, CONSENT_SELECTOR):
        return 'consent'
    if _is_account_type_page(page):
        return 'account_type'
    if _is_protect_account_page(page):
        return 'protect_account'
    if _is_proof_verify_page(page):
        return 'proof_verify'
    if _is_kmsi_only_page(page):
        return 'kmsi'
    if _is_passkey_login_prompt(page):
        return 'login_password'
    if _password_input(page) is not None:
        return 'login_password'
    if _is_login_email_page_loose(page):
        return 'login_email'
    return 'unknown'


def _handle_kmsi(page, log):
    try:
        from controllers.recovery_bind import is_kmsi_page, _click_kmsi_no
        if is_kmsi_page(page):
            if _click_kmsi_no(page, log=log):
                log('kmsi', '已点保持登录「否」', 'OK')
            else:
                log('kmsi', '点击「否」失败', 'WARN')
            page.wait(0.8)
    except Exception as exc:
        log('kmsi', f'处理异常: {_compact_exc(exc)}', 'WARN')
    return _current_auth_entry_state(page)


def _handle_proof_verify(page, log, temp_mail_cfg=None, recovery_session=None, failure_hook=None, captured_code=None):
    if _is_kmsi_only_page(page):
        return _handle_kmsi(page, log)

    log('proof_verify', '检测到「验证电子邮件/输入代码」页', 'WARN')

    if _click_use_password(page):
        st = _wait_after_use_password(page, log=log, captured_code=captured_code, timeout_ms=15000)
        if st == 'proof_verify':
            log('proof_verify', f'点击使用密码后仍为 {st}，继续按辅助邮箱验证兜底', 'WARN')
        elif st != 'unknown':
            log('proof_verify', f'已从验证页切到 {st}', 'OK')
            return st
        else:
            log('proof_verify', f'点击使用密码后状态={st}，继续按辅助邮箱验证兜底', 'WARN')

    session = recovery_session
    if not session or not session.get('address'):
        log('proof_verify', '无已保存的辅助邮箱会话，无法接码', 'FAIL')
        if failure_hook:
            try:
                failure_hook('recovery_bind_fail')
            except Exception:
                pass
        return _current_auth_entry_state(page)
    try:
        from controllers.recovery_bind import verify_bound_email_on_login
        ok = verify_bound_email_on_login(page, session, temp_mail_cfg or {}, log=log)
    except Exception as exc:
        log('proof_verify', f'验证异常: {_compact_exc(exc)}', 'FAIL')
        ok = False
    if ok:
        log('proof_verify', '辅助邮箱验证流程完成', 'OK')
    else:
        if failure_hook:
            try:
                failure_hook('recovery_bind_fail')
            except Exception:
                pass
        log('proof_verify', '辅助邮箱验证失败', 'FAIL')
    page.wait(0.5)
    return _current_auth_entry_state(page)


def _handle_protect_account(page, log, temp_mail_cfg=None, failure_hook=None, already_bound=False, current_email_local=''):
    if not _is_protect_account_page(page):
        return _current_auth_entry_state(page), None

    if already_bound:
        log('protect_account', '已有 recovery 记录，但当前 OAuth 页仍要求处理，先继续绑定/验证', 'WARN')
    else:
        log('protect_account', 'OAuth 出现保护帐户页（概率事件），尝试绑定', 'WARN')

    cfg = temp_mail_cfg or {}
    ok = False
    session = None
    if cfg.get('enabled', False):
        try:
            from controllers.recovery_bind import bind_recovery_email
            result = bind_recovery_email(page, cfg, log=log, local_name=(current_email_local or None))
            if isinstance(result, tuple):
                ok = bool(result[0])
                session = result[1] if len(result) > 1 else None
            else:
                ok = bool(result)
        except Exception as exc:
            log('protect_account', f'绑定异常: {_compact_exc(exc)}', 'FAIL')
            ok = False
            session = None

    if ok:
        log('protect_account', 'OAuth 阶段备用邮箱绑定成功', 'OK')
        page.wait(0.8)
    else:
        if failure_hook:
            try:
                failure_hook('recovery_bind_fail')
            except Exception:
                pass
        try:
            if _vis(page, '#iShowSkip'):
                D.click_sel(page, '#iShowSkip', timeout=4.0)
                log('protect_account', 'OAuth 绑定失败，已 #iShowSkip', 'WARN')
                page.wait(0.8)
        except Exception as exc:
            log('protect_account', f'跳过失败: {_compact_exc(exc)}', 'WARN')
    page.wait(0.5)
    st = _current_auth_entry_state(page)
    if ok and st == 'protect_account':
        try:
            if not _vis(page, '#EmailAddress') and not _vis(page, '#iOttText'):
                return 'unknown', session
        except Exception:
            pass
    return st, session


def _dump_auth_page(page, log, stage='auth_dump', observer=None):
    try:
        url = page.url or ''
    except Exception:
        url = ''
    body = ''
    try:
        body = D.body_text(page, limit=240).replace('\n', ' ')
    except Exception:
        body = ''
    state = _current_auth_entry_state(page)
    log(stage, f"state={state} url={url[:180]} body={body!r}", 'WARN')
    if observer:
        try:
            observer(stage, page)
        except Exception:
            pass
    return state


def _click_personal_account(page, log=None):
    clicked = False
    try:
        if _vis(page, MSA_TILE_SELECTOR):
            clicked = D.click_sel(page, MSA_TILE_SELECTOR, timeout=5)
            if clicked and log:
                log('account_type', '已点击 #msaTile 个人帐户', 'OK')
    except Exception as exc:
        if log:
            log('account_type', f'#msaTile 点击失败: {exc}', 'WARN')

    if not clicked:
        try:
            if _vis(page, MSA_TILE_TITLE_SELECTOR):
                clicked = D.click_sel(page, MSA_TILE_TITLE_SELECTOR, timeout=5)
                if clicked and log:
                    log('account_type', '已点击 #msaTileTitle', 'OK')
        except Exception:
            pass

    if not clicked:
        for text in ("个人帐户", "个人账户", "Personal account"):
            try:
                if D.click_role_button(page, text, timeout=1):
                    clicked = True
                    if log:
                        log('account_type', f'已点击 button:{text}', 'OK')
                    break
            except Exception:
                pass
            try:
                if D.click_if_visible(page, f'text:{text}'):
                    clicked = True
                    if log:
                        log('account_type', f'已点击 text:{text}', 'OK')
                    break
            except Exception:
                pass

    if clicked:
        try:
            page.wait(1.2)
        except Exception:
            pass
    elif log:
        log('account_type', '未找到可点击的个人帐户入口', 'WARN')
    return clicked


def _resolve_account_type(page, log, captured_code=None, max_rounds=3, observer=None):
    state = _current_auth_entry_state(page)
    for _ in range(max_rounds):
        if state != 'account_type':
            return state
        log('account_type', '检测到个人/工作帐户选择页，点击个人帐户', 'WARN')
        if not _click_personal_account(page, log):
            _dump_auth_page(page, log, 'account_type_dump', observer=observer)
            return 'account_type'
        try:
            _settle_auth_page(page, log, 'account_type')
        except Exception:
            page.wait(0.8)
        state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=15000, ignore_states=set())
        if state == 'unknown':
            state = _current_auth_entry_state(page)
    return state


def _settle_auth_page(page, log, stage, timeout_ms=AUTH_NAV_TIMEOUT_MS):
    try:
        page.wait.doc_loaded(timeout=timeout_ms / 1000)
    except Exception as exc:
        log(stage, f'等待 doc_loaded 超时，继续检测入口: {exc}', 'WARN')
    page.wait(1.2)


def _disable_auth_page_autofill(page, log=None):
    D.disable_autofill(page)
    if log:
        log('autofill', '已尝试关闭页面输入框自动填充提示', 'INFO')


def _submit_email_fill(page, full_email):
    _disable_auth_page_autofill(page)
    el = page.ele('css:' + EMAIL_SELECTOR, timeout=5)
    el.click()
    page.actions.type(Keys.ESCAPE)
    page.wait(0.15)
    el.clear()
    page.wait(0.1)
    el.input(full_email, clear=True)
    page.wait(0.3)
    page.actions.type(Keys.ESCAPE)
    page.wait(0.2)
    D.click_sel(page, EMAIL_NEXT_SELECTOR, timeout=5)


def _submit_email_type(page, full_email):
    _disable_auth_page_autofill(page)
    el = page.ele('css:' + EMAIL_SELECTOR, timeout=5)
    el.click()
    el.clear()
    page.wait(0.1)
    page.actions.click(el).type(full_email)
    page.wait(0.25)
    page.actions.type(Keys.ESCAPE)
    page.wait(0.2)
    D.click_sel(page, EMAIL_NEXT_SELECTOR, timeout=5)


def _submit_email_js_exact(page, full_email):
    el = page.ele('css:' + EMAIL_SELECTOR, timeout=10)
    _disable_auth_page_autofill(page)
    el.click()
    el.input(full_email, clear=True)
    page.wait(0.5)
    page.actions.type(Keys.ESCAPE)
    page.wait(0.2)
    D.click_sel(page, EMAIL_NEXT_SELECTOR, timeout=5)


def _submit_email(page, full_email, log, observer=None):
    if not D.q(page, EMAIL_SELECTOR, timeout=10):
        raise RuntimeError("邮箱框未出现")
    methods = [
        ("fill", _submit_email_fill),
        ("type", _submit_email_type),
        ("js_exact", _submit_email_js_exact),
        ("js_exact_retry", _submit_email_js_exact),
    ]
    success_states = ('login_password', 'consent', 'code', 'account_type', 'protect_account', 'proof_verify', 'kmsi')
    last_error = None
    last_stage = 'unknown'
    for name, method in methods:
        try:
            cur = _current_auth_entry_state(page)
            if cur in success_states:
                if cur == 'account_type':
                    cur = _resolve_account_type(page, log, observer=observer)
                log('oauth_email', f"提交前已在阶段={cur}", 'OK')
                return cur
            if D.count(page, EMAIL_SELECTOR) == 0:
                cur = _current_auth_entry_state(page)
                if cur == 'account_type':
                    cur = _resolve_account_type(page, log, observer=observer)
                return cur
            cur_el = D.q(page, EMAIL_SELECTOR)
            current = (cur_el.property('value') if cur_el else '') or ''
            log('oauth_email', f"尝试 {name}，提交前值={current.strip()!r}", 'INFO')
            method(page, full_email)
            stage = _wait_for_auth_entry_state(page, timeout_ms=12000)
            last_stage = stage
            if stage == 'account_type':
                stage = _resolve_account_type(page, log, observer=observer)
                last_stage = stage
            if stage in ('login_password', 'consent', 'code', 'protect_account', 'proof_verify', 'kmsi'):
                log('oauth_email', f"{name} 成功进入阶段={stage}", 'OK')
                return stage
            still_here = _vis(page, EMAIL_SELECTOR)
            err = ""
            if still_here:
                err_el = D.q(page, '#usernameError')
                err = (err_el.text if err_el else '') or ''
            log('oauth_email', f"{name} 后仍未进入下一阶段 stage={stage} error={err!r}", 'WARN')
        except Exception as exc:
            last_error = exc
            brief = _compact_exc(exc)
            log('oauth_email', f"{name} 失败: {brief}", 'WARN')
            stage = _current_auth_entry_state(page)
            if stage == 'account_type':
                stage = _resolve_account_type(page, log, observer=observer)
            last_stage = stage
            if stage in ('login_password', 'consent', 'code', 'protect_account', 'proof_verify', 'kmsi'):
                log('oauth_email', f"{name} 异常后已在阶段={stage}", 'OK')
                return stage
    if last_stage in ('login_password', 'consent', 'code', 'account_type', 'protect_account', 'proof_verify', 'kmsi'):
        if last_stage == 'account_type':
            last_stage = _resolve_account_type(page, log, observer=observer)
        return last_stage
    if last_error:
        raise RuntimeError(f"邮箱提交失败: {_compact_exc(last_error)}")
    raise RuntimeError("邮箱提交后未进入密码页")


def _click_alt_signin_method(page):
    for text in PASSKEY_ALT_METHOD_TEXTS:
        try:
            if D.click_role_button(page, text, timeout=0):
                page.wait(1.2)
                return True
        except Exception:
            pass
        try:
            if D.click_if_visible(page, f'text:{text}'):
                page.wait(1.2)
                return True
        except Exception:
            pass
    for sel in ('#idA_PWD_SwitchToPassword', '#idA_PWD_SwitchToCredPicker', '#iShowSkip'):
        try:
            if _vis(page, sel) and D.click_sel(page, sel, timeout=1.5):
                page.wait(1.2)
                return True
        except Exception:
            pass
    return False


def _wait_after_use_password(page, log=None, captured_code=None, timeout_ms=12000):
    state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=timeout_ms, ignore_states={'proof_verify'})
    if state == 'login_email' and not _vis(page, EMAIL_SELECTOR):
        state = _wait_for_real_login_entry(page, log=log, captured_code=captured_code, timeout_ms=6000)
    if state == 'unknown':
        state = _current_auth_entry_state(page)
    if log:
        try:
            log('oauth_password', f'点击使用密码后等待状态={state}', 'INFO')
        except Exception:
            pass
    return state


def _wait_for_real_login_entry(page, log=None, captured_code=None, timeout_ms=12000):
    deadline = time.time() + timeout_ms / 1000.0
    last_state = 'unknown'
    while time.time() < deadline:
        if captured_code and _wait_for_code_capture(page, captured_code, timeout_ms=0):
            return 'code'
        if _vis(page, EMAIL_SELECTOR):
            return 'login_email'
        if _password_input(page) is not None:
            return 'login_password'
        if _is_account_type_page(page):
            return 'account_type'
        if _is_protect_account_page(page):
            return 'protect_account'
        if _is_proof_verify_page(page):
            return 'proof_verify'
        if _is_kmsi_only_page(page):
            return 'kmsi'
        if _vis(page, CONSENT_SELECTOR):
            return 'consent'
        last_state = _current_auth_entry_state(page)
        page.wait(0.4)
    if _vis(page, EMAIL_SELECTOR):
        return 'login_email'
    if _password_input(page) is not None:
        return 'login_password'
    if _is_account_type_page(page):
        return 'account_type'
    if _is_protect_account_page(page):
        return 'protect_account'
    if _is_proof_verify_page(page):
        return 'proof_verify'
    if _is_kmsi_only_page(page):
        return 'kmsi'
    if _vis(page, CONSENT_SELECTOR):
        return 'consent'
    if log:
        try:
            log('login_entry', f'过渡页等待结束，最终仍未见真实邮箱框/密码框，last_state={last_state}', 'WARN')
        except Exception:
            pass
    return 'unknown'


def _describe_password_candidates(page):
    parts = []
    for selector in ('#passwordEntry', '#i0118', 'input[type="password"]'):
        try:
            items = D.q_all(page, selector)
            rows = []
            for idx, item in enumerate(items):
                meta = _password_input_meta(item)
                rows.append(f"{idx}:usable={_is_usable_password_input(item)},meta={meta}")
            parts.append(f"{selector} count={len(items)} [{' ; '.join(rows)}]")
        except Exception:
            parts.append(f"{selector} error")
    return ' | '.join(parts)


def _password_locator(page, log, timeout_ms=15000):
    deadline = time.time() + timeout_ms / 1000
    last_snapshot = ''
    while time.time() < deadline:
        _click_use_password(page)
        _dismiss_passkey_login_prompt(page, log=log)
        for selector in ('#passwordEntry', '#i0118', 'input[type="password"]', 'input[name="passwd"]'):
            for idx, item in enumerate(D.q_all(page, selector)):
                try:
                    if _is_usable_password_input(item):
                        log('oauth_password', f"使用密码框 {selector}[{idx}]", 'INFO')
                        return item, f"{selector}[{idx}]"
                except Exception:
                    continue
        item = _password_input(page)
        if item is not None:
            log('oauth_password', '使用密码框 fallback:_password_input', 'INFO')
            return item, 'fallback:_password_input'
        last_snapshot = _describe_password_candidates(page)
        page.wait(0.3)
    raise RuntimeError(f"未找到可见密码框：{last_snapshot}")


def _submit_password(page, password, log):
    _click_use_password(page)
    _disable_auth_page_autofill(page)
    log('oauth_password', f"密码候选快照：{_describe_password_candidates(page)}", 'INFO')
    locator, locator_name = _password_locator(page, log=log, timeout_ms=15000)
    try:
        locator.run_js(
            """function() {
                const el = this;
                el.removeAttribute('readonly');
                el.removeAttribute('aria-hidden');
                el.style.opacity = '1';
                el.style.pointerEvents = 'auto';
            }"""
        )
    except Exception:
        pass
    try:
        locator.click()
        locator.input(password, clear=True)
    except Exception:
        try:
            page.actions.click(locator).type(password)
        except Exception:
            pass
    page.wait(0.2)
    try:
        filled_len = len(locator.property('value') or '')
        log('oauth_password', f"{locator_name} 已写入密码，长度={filled_len}", 'INFO')
    except Exception:
        log('oauth_password', f"{locator_name} 已写入密码", 'INFO')
    page.wait(0.4)
    try:
        btn = D.q(page, '[data-testid="primaryButton"]', timeout=5)
        if btn:
            btn.click()
            log('oauth_password', '点击 data-testid=primaryButton 提交密码', 'INFO')
        else:
            raise RuntimeError('no primaryButton')
    except Exception:
        try:
            page.actions.type(Keys.ENTER)
        except Exception:
            pass
        log('oauth_password', '主按钮点击失败，改用 Enter 提交密码', 'WARN')


def _has_invalid_password(page):
    return any(_text_exists(page, t) for t in PASSWORD_WRONG_TEXTS)


def _has_password_login_blocked(page):
    return any(_text_exists(page, t) for t in PASSWORD_BLOCKED_TEXTS)


def _has_unknown_account(page):
    return (
        _text_exists(page, '找不到使用该用户名的帐户')
        or _text_exists(page, '找不到使用该用户名的账户')
        or _text_exists(page, "We couldn't find an account with that username")
        or _text_exists(page, "That Microsoft account doesn't exist")
        or _vis(page, '#usernameError')
    )


def _dismiss_passkey_setup(page, log=None):
    try:
        url = page.url or ''
    except Exception:
        url = ''
    try:
        body = D.body_text(page, limit=1400) or ''
    except Exception:
        body = ''
    passkey_hint = any(
        k in body for k in (
            '通行密钥', 'Windows Hello', 'passkey', 'Passkey',
            '更快速地登录', 'face, fingerprint', 'security key',
            '使用 Windows Hello', '创建通行密钥', '设置通行密钥',
            'Save a passkey', 'Create a passkey', 'Set up a passkey',
        )
    ) or 'fido/create' in url or 'passkey' in url.lower()
    if not passkey_hint and 'fido' not in url:
        return False
    if log:
        log('passkey', f'检测到密钥创建页 url={url[:120]}', 'WARN')

    try:
        back = D.q(page, '#idBtn_Back')
        if back and back.states.is_displayed:
            value = ''
            try:
                value = ((back.attr('value') or '') + ' ' + (back.text or '')).strip()
            except Exception:
                value = ''
            if any(k in value for k in ('取消', 'Cancel', 'No', 'not now', 'Not now', '暂时不要')) and D.click_sel(page, '#idBtn_Back', timeout=2.0):
                page.wait(1.0)
                if log:
                    log('passkey', f'已点击 #idBtn_Back value={value[:40]!r}', 'OK')
                return True
    except Exception:
        pass

    for sel in ('#iCancel', '#iShowSkip'):
        try:
            if _vis(page, sel) and D.click_sel(page, sel, timeout=2.0):
                page.wait(1.0)
                if log:
                    log('passkey', f'已点击跳过 {sel}', 'OK')
                return True
        except Exception:
            pass

    for text in ('取消', 'Cancel', '暂时不要', 'Not now', 'Skip for now', 'Maybe later', '以后再说', '暂时跳过', '现在跳过', '跳过', 'Skip'):
        try:
            if D.click_role_button(page, text, timeout=0):
                page.wait(1.0)
                if log:
                    log('passkey', f'已点击 {text}', 'OK')
                return True
        except Exception:
            pass
        try:
            if D.click_if_visible(page, f'text:{text}'):
                page.wait(1.0)
                if log:
                    log('passkey', f'已点击 text:{text}', 'OK')
                return True
        except Exception:
            pass
        try:
            if D.click_if_visible(page, f'input[type="button"][value="{text}"]'):
                page.wait(1.0)
                if log:
                    log('passkey', f'已点击 input:{text}', 'OK')
                return True
        except Exception:
            pass

    if '尝试使用密钥登录时出错' in body or "We couldn't sign you in" in body:
        for text in ('后退', 'Back', '返回'):
            try:
                if D.click_role_button(page, text, timeout=0) or D.click_if_visible(page, f'text:{text}'):
                    page.wait(1.0)
                    if log:
                        log('passkey', f'已从密钥失败页返回: {text}', 'WARN')
                    return True
            except Exception:
                pass
    return False


def _digest_post_email_states(page, log, state, captured_code=None, temp_mail_cfg=None,
                              recovery_already_bound=False, recovery_session=None,
                              failure_hook=None, rounds=4, current_email_local='', observer=None):
    session = recovery_session
    for _ in range(rounds):
        if state == 'account_type':
            state = _resolve_account_type(page, log, captured_code=captured_code, observer=observer)
            log('account_type', f'处理后状态={state}', 'INFO')
            continue
        if state == 'protect_account':
            state, new_session = _handle_protect_account(
                page, log, temp_mail_cfg=temp_mail_cfg, failure_hook=failure_hook,
                already_bound=recovery_already_bound, current_email_local=current_email_local,
            )
            if new_session:
                session = new_session
                recovery_already_bound = True
            log('protect_account', f'处理后状态={state}', 'INFO')
            continue
        if state == 'proof_verify':
            state = _handle_proof_verify(page, log, temp_mail_cfg=temp_mail_cfg,
                                         recovery_session=session, failure_hook=failure_hook,
                                         captured_code=captured_code)
            log('proof_verify', f'处理后状态={state}', 'INFO')
            continue
        if state == 'kmsi':
            state = _handle_kmsi(page, log)
            log('kmsi', f'处理后状态={state}', 'INFO')
            continue
        if state == 'unknown':
            if _dismiss_passkey_login_prompt(page, log=log):
                state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=12000)
                continue
            if _dismiss_passkey_setup(page, log):
                state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=12000)
                continue
            try:
                from controllers.recovery_bind import is_kmsi_page, _click_kmsi_no
                if is_kmsi_page(page):
                    _click_kmsi_no(page, log=log)
                    state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=8000)
                    continue
            except Exception:
                pass
        break
    return state, session


def _perform_login_after_cookie_fail(page, full_email, password, log, failure_hook=None, state='login_email',
                                     captured_code=None, temp_mail_cfg=None,
                                     recovery_already_bound=False, recovery_session=None,
                                     observer=None):
    current_email_local = (str(full_email or '').split('@', 1)[0]).strip()
    state, recovery_session = _digest_post_email_states(
        page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
        recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
        failure_hook=failure_hook, rounds=4, current_email_local=current_email_local,
        observer=observer,
    )

    if state == 'login_email':
        log('login_email', '开始输入邮箱', 'WARN')
        try:
            email_stage = _submit_email(page, full_email, log, observer=observer)
        except Exception as exc:
            log('login_email', f'邮箱提交异常: {_compact_exc(exc)}', 'WARN')
            state = _current_auth_entry_state(page)
            state, recovery_session = _digest_post_email_states(
                page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
                recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
                failure_hook=failure_hook, rounds=4, current_email_local=current_email_local,
                observer=observer,
            )
            email_stage = state
        if email_stage in ('login_password', 'consent', 'code', 'account_type', 'protect_account', 'proof_verify', 'kmsi'):
            state = email_stage
        else:
            state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=AUTH_ENTRY_TIMEOUT_MS, ignore_states={'login_email'})
        state, recovery_session = _digest_post_email_states(
            page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
            recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
            failure_hook=failure_hook, rounds=4, current_email_local=current_email_local,
            observer=observer,
        )
        log('login_email', f'邮箱提交后状态={state}', 'INFO')
        if _has_unknown_account(page):
            _dump_auth_page(page, log, observer=observer)
            log('login_email', '邮箱不存在', 'FAIL')
            return False, recovery_session
        if state == 'login_email':
            if failure_hook:
                failure_hook('oauth_login_timeout')
            _dump_auth_page(page, log, observer=observer)
            log('login_email', '邮箱页停留超时', 'FAIL')
            return False, recovery_session

    state, recovery_session = _digest_post_email_states(
        page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
        recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
        failure_hook=failure_hook, rounds=3, observer=observer,
    )

    if state == 'login_password':
        if _has_password_login_blocked(page):
            if _dismiss_passkey_login_prompt(page, log=log):
                state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=AUTH_ENTRY_TIMEOUT_MS, ignore_states={'login_password'})
                state, recovery_session = _digest_post_email_states(
                    page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
                    recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
                    failure_hook=failure_hook, rounds=2, current_email_local=current_email_local,
                    observer=observer,
                )
            if state in ('consent', 'code'):
                return True, recovery_session
            if failure_hook:
                failure_hook('oauth_password_blocked')
            _dump_auth_page(page, log, observer=observer)
            log('login_password', '密码登录不可用，跳过硬填', 'FAIL')
            return False, recovery_session
        log('login_password', '开始输入密码', 'WARN')
        _submit_password(page, password, log)
        if _has_password_login_blocked(page):
            if failure_hook:
                failure_hook('oauth_password_blocked')
            _dump_auth_page(page, log, observer=observer)
            log('login_password', '检测到密码登录不可用', 'FAIL')
            return False, recovery_session
        if _has_invalid_password(page):
            if failure_hook:
                failure_hook('oauth_password_wrong')
            _dump_auth_page(page, log, observer=observer)
            log('login_password', '检测到密码错误提示', 'FAIL')
            return False, recovery_session
        state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=AUTH_ENTRY_TIMEOUT_MS, ignore_states={'login_password'})
        state, recovery_session = _digest_post_email_states(
            page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
            recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
            failure_hook=failure_hook, rounds=4, current_email_local=current_email_local,
            observer=observer,
        )
        log('login_password', f'密码提交后状态={state}', 'INFO')
        if state == 'code':
            return True, recovery_session
        if state != 'consent':
            if state == 'unknown':
                state = _wait_for_auth_state_or_code(
                    page, captured_code, timeout_ms=12000, ignore_states={'login_password'}
                )
                state, recovery_session = _digest_post_email_states(
                    page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
                    recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
                    failure_hook=failure_hook, rounds=3, current_email_local=current_email_local,
                    observer=observer,
                )
                log('login_password', f'密码提交后二次等待状态={state}', 'INFO')
                if state in ('code', 'consent'):
                    return True, recovery_session
            if _has_password_login_blocked(page):
                if failure_hook:
                    failure_hook('oauth_password_blocked')
                _dump_auth_page(page, log, observer=observer)
                log('login_password', '密码提交后：密码登录不可用', 'FAIL')
            elif _has_invalid_password(page):
                if failure_hook:
                    failure_hook('oauth_password_wrong')
                _dump_auth_page(page, log, observer=observer)
                log('login_password', '检测到密码错误提示', 'FAIL')
            else:
                if failure_hook:
                    failure_hook('oauth_consent_fail')
                _dump_auth_page(page, log, observer=observer)
                log('login_password', f'未进入同意页面 final_state={state}', 'FAIL')
            return False, recovery_session

    if state in ('proof_verify', 'kmsi'):
        state, recovery_session = _digest_post_email_states(
            page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
            recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
            failure_hook=failure_hook, rounds=4, current_email_local=current_email_local,
            observer=observer,
        )
        log('proof_verify', f'proof/kmsi 处理后状态={state}', 'INFO')
        if state == 'login_password' and not _has_password_login_blocked(page):
            log('login_password', 'proof 后出现密码页，继续填写', 'WARN')
            _submit_password(page, password, log)
            state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=AUTH_ENTRY_TIMEOUT_MS, ignore_states={'login_password'})
            state, recovery_session = _digest_post_email_states(
                page, log, state, captured_code=captured_code, temp_mail_cfg=temp_mail_cfg,
                recovery_already_bound=recovery_already_bound, recovery_session=recovery_session,
                failure_hook=failure_hook, rounds=3, observer=observer,
            )
        if state in ('code', 'consent'):
            return True, recovery_session
        if failure_hook:
            failure_hook('oauth_consent_fail')
        _dump_auth_page(page, log, observer=observer)
        log('proof_verify', f'验证后未进入同意页 final_state={state}', 'FAIL')
        return False, recovery_session

    return state in ('consent', 'code'), recovery_session


def _exchange_code_once(code, proxy_url=None, timeout_sec=20):
    proxies = None
    if proxy_url:
        proxies = {'http': proxy_url, 'https': proxy_url}
    response = requests.post(
        TOKEN_URL,
        data={
            'client_id': CLIENT_ID,
            'code': code,
            'redirect_uri': REDIRECT_URI,
            'grant_type': 'authorization_code',
            'scope': TOKEN_SCOPE,
        },
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        timeout=timeout_sec,
        proxies=proxies,
    )
    response.raise_for_status()
    return response.json()


def _exchange_code_with_retry(code, log, failure_hook=None, current_proxy='', token_proxy_getter=None):
    proxy_candidates = []
    saw_network_error = False
    for item in (current_proxy,):
        if item and item not in proxy_candidates:
            proxy_candidates.append(item)
    if token_proxy_getter:
        for _ in range(2):
            try:
                picked = token_proxy_getter(exclude=proxy_candidates[-1] if proxy_candidates else current_proxy)
            except TypeError:
                picked = token_proxy_getter()
            except Exception as exc:
                log('token', f'获取新代理失败: {exc}', 'WARN')
                picked = ''
            if picked and picked not in proxy_candidates:
                proxy_candidates.append(picked)
    proxy_candidates.append('')
    total_attempts = len(proxy_candidates)
    last_error = None
    for idx, proxy_url in enumerate(proxy_candidates):
        proxy_text = proxy_url or 'direct'
        try:
            log('token', f'开始换 token 第 {idx + 1}/{total_attempts} 次 proxy={proxy_text}', 'INFO')
            data = _exchange_code_once(code, proxy_url=proxy_url or None, timeout_sec=20)
            if 'refresh_token' not in data:
                last_error = RuntimeError(data.get('error_description') or data.get('error') or 'unknown')
                log('token', f"token请求失败 proxy={proxy_text}: {data.get('error', 'unknown')}", 'WARN')
                if idx < total_attempts - 1:
                    time.sleep(1.5 + idx)
                    continue
                break
            return True, data['refresh_token']
        except (requests.exceptions.SSLError, requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_error = exc
            saw_network_error = True
            log('token', f'网络异常 proxy={proxy_text}: {exc}', 'WARN')
            if idx < total_attempts - 1:
                time.sleep(1.5 + idx)
                continue
        except Exception as exc:
            last_error = exc
            log('token', f'换 token 异常 proxy={proxy_text}: {exc}', 'WARN')
            if idx < total_attempts - 1:
                time.sleep(1.5 + idx)
                continue
    if saw_network_error and failure_hook:
        failure_hook('oauth_token_network_fail')
    if failure_hook:
        failure_hook('oauth_token_fail')
    log('token', f'最终换 token 失败: {last_error}', 'FAIL')
    return False, None


def _handle_auth_entry_state(page, log, state, captured_code=None, temp_mail_cfg=None,
                             failure_hook=None, recovery_already_bound=False,
                             recovery_session=None, current_email_local='', observer=None):
    if state == 'account_type':
        state = _resolve_account_type(page, log, captured_code=captured_code, observer=observer)
        log('entry', f'帐户类型处理后状态={state}')
    if state == 'protect_account':
        state, new_recovery_session = _handle_protect_account(
            page, log, temp_mail_cfg=temp_mail_cfg, failure_hook=failure_hook,
            already_bound=recovery_already_bound, current_email_local=current_email_local,
        )
        if new_recovery_session:
            recovery_session = new_recovery_session
            recovery_already_bound = True
        log('entry', f'保护帐户处理后状态={state}')
    if state == 'proof_verify':
        state = _handle_proof_verify(
            page, log, temp_mail_cfg=temp_mail_cfg,
            recovery_session=recovery_session, failure_hook=failure_hook,
            captured_code=captured_code,
        )
        log('entry', f'proof 验证后状态={state}')
    if state == 'kmsi':
        state = _handle_kmsi(page, log)
        log('entry', f'kmsi 处理后状态={state}')
    return state, recovery_session, recovery_already_bound


def _finalize_oauth_flow(page, log, state, captured_code, failure_hook=None,
                         current_proxy='', token_proxy_getter=None, observer=None):
    if state == 'code':
        return _exchange_captured_code(
            page,
            captured_code,
            log,
            failure_hook=failure_hook,
            current_proxy=current_proxy,
            token_proxy_getter=token_proxy_getter,
        )
    if state == 'consent':
        return _click_consent_and_exchange(
            page,
            captured_code,
            log,
            failure_hook=failure_hook,
            current_proxy=current_proxy,
            token_proxy_getter=token_proxy_getter,
        )
    if failure_hook:
        failure_hook('oauth_consent_fail')
    _dump_auth_page(page, log, observer=observer)
    log('entry', f'未进入同意或登录页面，最终状态={state}', 'FAIL')
    return False, None


def _click_consent_and_exchange(page, captured_code, log, failure_hook=None, current_proxy='', token_proxy_getter=None):
    D.start_code_listen(page)
    accept_btn = page.ele('css:' + CONSENT_SELECTOR, timeout=60)
    if not accept_btn:
        if failure_hook:
            failure_hook('oauth_consent_fail')
        log('consent', '同意按钮未出现', 'FAIL')
        return False, None
    try:
        accept_btn.click()
    except Exception:
        accept_btn.click(by_js=True)
    log('consent', '点击接受授权', 'OK')

    code = _wait_for_code_capture(page, captured_code, timeout_ms=180000)
    if not code:
        if failure_hook:
            failure_hook('oauth_code_fail')
        log('callback', '3分钟内未捕获到code', 'FAIL')
        return False, None

    log('callback', '捕获到code', 'OK')
    return _exchange_code_with_retry(
        code,
        log=log,
        failure_hook=failure_hook,
        current_proxy=current_proxy,
        token_proxy_getter=token_proxy_getter,
    )


def _exchange_captured_code(page, captured_code, log, failure_hook=None, current_proxy='', token_proxy_getter=None):
    code = _wait_for_code_capture(page, captured_code, timeout_ms=1000, poll_ms=100)
    if not code:
        return False, None
    log('callback', '已直接捕获到code，跳过同意页', 'OK')
    return _exchange_code_with_retry(
        code,
        log=log,
        failure_hook=failure_hook,
        current_proxy=current_proxy,
        token_proxy_getter=token_proxy_getter,
    )


def get_oauth2_token_cold(page, full_email, password, prefix='', failure_hook=None, log_hook=None,
                          observer=None, current_proxy='', token_proxy_getter=None,
                          temp_mail_cfg=None, recovery_already_bound=False, recovery_session=None):
    """无 cookie 冷启动 OAuth：一页内完成登录 / protect / proof / kmsi / consent / code。"""
    auth_url = build_auth_url(login_hint=full_email)
    current_email_local = (str(full_email or '').split('@', 1)[0]).strip()
    captured_code = [None]

    def _log(stage, message, level='INFO'):
        if log_hook:
            log_hook(stage, message, level)
            return
        tag = prefix if prefix else '[OAuth2:COLD]'
        print(f"{tag}[{level}] {time.strftime('%H:%M:%S')} | {stage} | {message}")

    D.start_code_listen(page)

    try:
        _log('start', '开始 OAuth2（无 cookie 冷启动）')
        page.get(auth_url)
        _settle_auth_page(page, _log, 'goto')
        _disable_auth_page_autofill(page, _log)
        _log('goto', '进入auth页面')

        state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=AUTH_ENTRY_TIMEOUT_MS)
        _log('entry', f'首次检测状态={state}')

        state, recovery_session, recovery_already_bound = _handle_auth_entry_state(
            page,
            _log,
            state,
            captured_code=captured_code,
            temp_mail_cfg=temp_mail_cfg,
            failure_hook=failure_hook,
            recovery_already_bound=recovery_already_bound,
            recovery_session=recovery_session,
            current_email_local=current_email_local,
            observer=observer,
        )

        if state == 'unknown' and _is_login_email_page_loose(page):
            state = 'login_email'
            _log('entry', 'unknown 实为邮箱登录页：同页补登当前邮箱', 'WARN')
        elif state == 'unknown':
            _dump_auth_page(page, _log, 'entry_unknown', observer=observer)
            if _is_account_type_page(page):
                state = 'account_type'
            elif _is_protect_account_page(page):
                state = 'protect_account'
            elif _is_proof_verify_page(page):
                state = 'proof_verify'
            elif _is_kmsi_only_page(page):
                state = 'kmsi'
            elif _is_login_email_page_loose(page):
                state = 'login_email'
                _log('entry', 'unknown 实为邮箱登录页：同页补登当前邮箱', 'WARN')
            state, recovery_session, recovery_already_bound = _handle_auth_entry_state(
                page,
                _log,
                state,
                captured_code=captured_code,
                temp_mail_cfg=temp_mail_cfg,
                failure_hook=failure_hook,
                recovery_already_bound=recovery_already_bound,
                recovery_session=recovery_session,
                current_email_local=current_email_local,
                observer=observer,
            )
            _log('entry', f'处理后状态={state}')

        if state in ('login_email', 'login_password', 'account_type', 'protect_account', 'proof_verify', 'kmsi'):
            ok, recovery_session = _perform_login_after_cookie_fail(
                page,
                full_email,
                password,
                _log,
                failure_hook=failure_hook,
                state=state,
                captured_code=captured_code,
                temp_mail_cfg=temp_mail_cfg,
                recovery_already_bound=recovery_already_bound,
                recovery_session=recovery_session,
                observer=observer,
            )
            if not ok:
                return False, None, recovery_session
            state = _wait_for_auth_state_or_code(page, captured_code, timeout_ms=8000)
            state, recovery_session = _digest_post_email_states(
                page,
                _log,
                state,
                captured_code=captured_code,
                temp_mail_cfg=temp_mail_cfg,
                recovery_already_bound=recovery_already_bound,
                recovery_session=recovery_session,
                failure_hook=failure_hook,
                rounds=3,
                observer=observer,
            )
            _log('entry', f'登录后阶段={state}', 'INFO')

        ok, refresh_token = _finalize_oauth_flow(
            page,
            _log,
            state,
            captured_code,
            failure_hook=failure_hook,
            current_proxy=current_proxy,
            token_proxy_getter=token_proxy_getter,
            observer=observer,
        )
        if ok:
            _log('token', 'token获取成功!', 'OK')
            return True, refresh_token, recovery_session
        return False, None, recovery_session
    except Exception as exc:
        _log('exception', f'异常: {_compact_exc(exc)}', 'FAIL')
        return False, None, recovery_session
    finally:
        try:
            page.listen.stop()
        except Exception:
            pass
