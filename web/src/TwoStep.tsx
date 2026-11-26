import { useEffect, useState, type FormEvent } from 'react';
import { KeyRound, ShieldCheck } from 'lucide-react';

// Two-step sign-in (authenticator app) for dashboard accounts. The server side is backend/app/features/mfa_accounts.py,
// the rules and the runbook are in docs/OPERATIONS.md section 9. There is no QR code: the setup key is typed into the
// authenticator app, or the otpauth link opens the app on the same phone.

type Lang = 'en' | 'ar';
type SignedIn = { access_token: string; user: any; recovery_codes_remaining?: number; used_recovery_code?: boolean; recovery_codes?: string[] };
type Status = { available: boolean; enabled: boolean; required: boolean; pending_setup: boolean; recovery_codes_remaining: number; issuer: string };
type Started = { secret: string; secret_grouped: string; otpauth_uri: string; issuer: string; account: string };

async function call(api: string, token: string, path: string, method: 'GET' | 'POST', body?: unknown) {
  const response = await fetch(`${api}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
  return data;
}

const texts = (lang: Lang) => (en: string, ar: string) => (lang === 'ar' ? ar : en);

/** The 10 recovery codes, shown once. The person must confirm that they have saved them. */
function RecoveryCodes({ lang, codes, onContinue, label }: { lang: Lang; codes: string[]; onContinue: () => void; label?: string }) {
  const t = texts(lang);
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = codes.join('\n');
  return <div className="nuqati-account-card" role="group" aria-label={t('Recovery codes', 'رموز الاسترداد')}>
    <div className="nuqati-account-card-heading"><div><h4>{t('Save your recovery codes', 'احفظ رموز الاسترداد')}</h4>
      <p>{t('Each code works once, if you lose your phone. They are shown only now. Print them or keep them in a password manager.', 'يعمل كل رمز مرة واحدة إذا فقدت هاتفك. تظهر الآن فقط. اطبعها أو احفظها في مدير كلمات المرور.')}</p></div></div>
    <pre dir="ltr" style={{ fontFamily: 'monospace', fontSize: 16, lineHeight: 1.7, userSelect: 'all', margin: '8px 0' }}>{text}</pre>
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      <button type="button" className="refresh" onClick={() => { void navigator.clipboard?.writeText(text).then(() => setCopied(true)).catch(() => setCopied(false)); }}>
        {copied ? t('Copied', 'تم النسخ') : t('Copy codes', 'نسخ الرموز')}</button>
      <button type="button" className="refresh" onClick={() => window.print()}>{t('Print', 'طباعة')}</button>
    </div>
    <label style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '10px 0' }}><input type="checkbox" checked={saved} onChange={e => setSaved(e.target.checked)} />
      {t('I have saved these codes', 'لقد حفظت هذه الرموز')}</label>
    <button type="button" className="primary" disabled={!saved} onClick={onContinue}>{label || t('Continue', 'متابعة')}</button>
  </div>;
}

/** Start (and confirm) the setup. `needsPassword`: re-enter the password (signed-in session); `changing`: also a code of the current authenticator. */
export function TwoStepSetup({ lang, api, token, needsPassword, changing, onDone, onCancel, continueLabel }:
  { lang: Lang; api: string; token: string; needsPassword: boolean; changing?: boolean; onDone: (reply: SignedIn) => void; onCancel?: () => void; continueLabel?: string }) {
  const t = texts(lang);
  const [password, setPassword] = useState('');
  const [currentCode, setCurrentCode] = useState('');
  const [started, setStarted] = useState<Started | null>(null);
  const [code, setCode] = useState('');
  const [reply, setReply] = useState<(SignedIn & { recovery_codes: string[] }) | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function start(e: FormEvent) {
    e.preventDefault(); setError(''); setBusy(true);
    try {
      const body: Record<string, string> = {};
      if (needsPassword) body.password = password;
      if (changing) body.code = currentCode;
      setStarted(await call(api, token, '/api/v1/auth/mfa/enroll', 'POST', body)); setPassword(''); setCurrentCode('');
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  async function confirm(e: FormEvent) {
    e.preventDefault(); setError(''); setBusy(true);
    try { setReply(await call(api, token, '/api/v1/auth/mfa/confirm', 'POST', { code })); setCode(''); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }

  if (reply) return <RecoveryCodes lang={lang} codes={reply.recovery_codes} label={continueLabel} onContinue={() => onDone(reply)} />;
  if (!started) return <form className="nuqati-account-card" onSubmit={start}>
    <div className="nuqati-account-card-heading"><div><h4>{changing ? t('Change authenticator', 'تغيير تطبيق المصادقة') : t('Set up two-step sign-in', 'إعداد تسجيل الدخول بخطوتين')}</h4>
      <p>{t('You need an authenticator app on your phone (Google Authenticator, Microsoft Authenticator, Authy, 1Password ...).', 'تحتاج إلى تطبيق مصادقة على هاتفك (Google Authenticator أو Microsoft Authenticator أو Authy ...).')}</p></div></div>
    {needsPassword && <label>{t('Current password', 'كلمة المرور الحالية')}<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>}
    {changing && <label>{t('Code from your current authenticator', 'الرمز من تطبيق المصادقة الحالي')}<input inputMode="numeric" autoComplete="one-time-code" required value={currentCode} onChange={e => setCurrentCode(e.target.value)} /></label>}
    {error && <div className="notice" role="alert">{error}</div>}
    <div style={{ display: 'flex', gap: 8 }}><button className="primary" type="submit" disabled={busy}>{t('Show the setup key', 'عرض مفتاح الإعداد')}</button>
      {onCancel && <button type="button" className="refresh" onClick={onCancel}>{t('Cancel', 'إلغاء')}</button>}</div>
  </form>;
  return <form className="nuqati-account-card" onSubmit={confirm}>
    <div className="nuqati-account-card-heading"><div><h4>{t('Add Nuqati to your authenticator app', 'أضف نقاطي إلى تطبيق المصادقة')}</h4>
      <p>{t('In the app choose "Add account", then "Enter a setup key", and type this key (time-based):', 'في التطبيق اختر "إضافة حساب" ثم "إدخال مفتاح الإعداد" واكتب هذا المفتاح (زمني):')}</p></div></div>
    <pre dir="ltr" style={{ fontFamily: 'monospace', fontSize: 20, letterSpacing: 1, userSelect: 'all', margin: '8px 0' }}>{started.secret_grouped}</pre>
    <p dir="ltr" style={{ margin: '0 0 8px' }}><small>{started.issuer} · {started.account}</small></p>
    <p><a href={started.otpauth_uri}>{t('On this phone? Open it in the authenticator app', 'على هذا الهاتف؟ افتحه في تطبيق المصادقة')}</a></p>
    <label>{t('Enter the 6-digit code the app shows now', 'أدخل الرمز المكون من 6 أرقام الذي يعرضه التطبيق الآن')}
      <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]*" maxLength={7} required value={code} onChange={e => setCode(e.target.value)} /></label>
    {error && <div className="notice" role="alert">{error}</div>}
    <div style={{ display: 'flex', gap: 8 }}><button className="primary" type="submit" disabled={busy}>{t('Confirm and finish', 'تأكيد وإنهاء')}</button>
      {onCancel && <button type="button" className="refresh" onClick={onCancel}>{t('Cancel', 'إلغاء')}</button>}</div>
  </form>;
}

/** The sign-in screen after the password: the code step, or the compulsory setup of a required role. */
export function TwoStepSignIn({ lang, api, kind, mfaToken, onSignedIn, onCancel, logo }:
  { lang: Lang; api: string; kind: 'code' | 'setup'; mfaToken: string; onSignedIn: (data: SignedIn) => void; onCancel: () => void; logo?: string }) {
  const t = texts(lang);
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<SignedIn | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault(); setError(''); setBusy(true);
    try {
      const data: SignedIn = await call(api, '', '/api/v1/auth/login/mfa', 'POST', { mfa_token: mfaToken, code });
      if (data.used_recovery_code) setNotice(data); else onSignedIn(data);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); setCode(''); } finally { setBusy(false); }
  }

  return <div className="login-screen" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
    {kind === 'setup'
      ? <div className="login-card" style={{ maxWidth: 520 }}>
        {logo && <img src={logo} alt="Nuqati" />}
        <h2>{t('Two-step sign-in is required', 'تسجيل الدخول بخطوتين مطلوب')}</h2>
        <p>{t('Your role must use an authenticator app. Set it up now to finish signing in.', 'يجب على دورك استخدام تطبيق المصادقة. أعده الآن لإكمال تسجيل الدخول.')}</p>
        <TwoStepSetup lang={lang} api={api} token={mfaToken} needsPassword={false} onDone={reply => onSignedIn(reply)} onCancel={onCancel} continueLabel={t('Continue to Nuqati', 'متابعة إلى نقاطي')} />
      </div>
      : notice
        ? <div className="login-card"><ShieldCheck size={28} /><h2>{t('You signed in with a recovery code', 'سجلت الدخول برمز استرداد')}</h2>
          <p>{t(`${notice.recovery_codes_remaining ?? 0} recovery codes are left. Under My account you can change your authenticator and get new codes.`, `تبقى ${notice.recovery_codes_remaining ?? 0} رموز استرداد. من حسابي يمكنك تغيير تطبيق المصادقة والحصول على رموز جديدة.`)}</p>
          <button className="primary" type="button" onClick={() => onSignedIn(notice)}>{t('Continue', 'متابعة')}</button></div>
        : <form className="login-card" onSubmit={submit}>
          {logo && <img src={logo} alt="Nuqati" />}
          <h2>{t('Two-step sign-in', 'تسجيل الدخول بخطوتين')}</h2>
          <p>{t('Enter the 6-digit code from your authenticator app, or one of your recovery codes.', 'أدخل الرمز المكون من 6 أرقام من تطبيق المصادقة، أو أحد رموز الاسترداد.')}</p>
          <label>{t('Code', 'الرمز')}<input autoFocus inputMode="text" autoComplete="one-time-code" required maxLength={20} value={code} onChange={e => setCode(e.target.value)} /></label>
          {error && <div className="notice" role="alert">{error}</div>}
          <button className="primary" type="submit" disabled={busy}>{t('Sign in', 'تسجيل الدخول')}</button>
          <button type="button" className="refresh" onClick={onCancel}>{t('Back', 'رجوع')}</button>
        </form>}
  </div>;
}

/** "My account": status, setup, change authenticator, new recovery codes, switch off. `onSessionsEnded` after a switch-off (the server ends the sessions). */
export function TwoStepPanel({ lang, api, token, onSessionsEnded }: { lang: Lang; api: string; token: string; onSessionsEnded: () => void }) {
  const t = texts(lang);
  const [status, setStatus] = useState<Status | null>(null);
  const [view, setView] = useState<'home' | 'setup' | 'change' | 'codes' | 'off'>('home');
  const [codes, setCodes] = useState<string[] | null>(null);
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    try { setStatus(await call(api, token, '/api/v1/auth/mfa', 'GET')); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
  }
  useEffect(() => { void load(); }, []);
  const back = () => { setView('home'); setPassword(''); setCode(''); setError(''); void load(); };

  async function secure(path: string, after: (data: any) => void) {
    setError(''); setBusy(true);
    try { after(await call(api, token, path, 'POST', { password, code })); setPassword(''); setCode(''); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }

  const heading = <div className="nuqati-account-card-heading"><div><h4><KeyRound size={16} aria-hidden="true" /> {t('Two-step sign-in', 'تسجيل الدخول بخطوتين')}</h4></div></div>;
  if (!status) return <div className="nuqati-account-card">{heading}{error ? <div className="notice" role="alert">{error}</div> : <p>{t('Loading ...', 'جارٍ التحميل ...')}</p>}</div>;
  if (!status.available) return <div className="nuqati-account-card">{heading}<p>{t('Two-step sign-in is not switched on on this server. Ask your administrator.', 'تسجيل الدخول بخطوتين غير مفعل على هذا الخادم. اسأل المسؤول.')}</p></div>;

  if (view === 'setup' || view === 'change') return <TwoStepSetup lang={lang} api={api} token={token} needsPassword changing={view === 'change'} onCancel={back}
    onDone={() => back()} />;  // the setup has just shown the recovery codes itself
  if (codes) return <RecoveryCodes lang={lang} codes={codes} onContinue={() => setCodes(null)} />;

  if (view === 'codes' || view === 'off') {
    const off = view === 'off';
    return <form className="nuqati-account-card" onSubmit={e => {
      e.preventDefault();
      void secure(off ? '/api/v1/auth/mfa/disable' : '/api/v1/auth/mfa/recovery-codes', data => { if (off) onSessionsEnded(); else { setCodes(data.recovery_codes); back(); } });
    }}>
      {heading}
      <p>{off ? t('Switching it off ends all your sessions. Enter your password and a code to confirm.', 'إيقافه ينهي جميع جلساتك. أدخل كلمة المرور ورمزاً للتأكيد.')
        : t('New recovery codes replace all the old ones. Enter your password and a code to confirm.', 'الرموز الجديدة تحل محل القديمة. أدخل كلمة المرور ورمزاً للتأكيد.')}</p>
      <label>{t('Current password', 'كلمة المرور الحالية')}<input type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} /></label>
      <label>{t('Code from your authenticator (or a recovery code)', 'الرمز من تطبيق المصادقة (أو رمز استرداد)')}<input autoComplete="one-time-code" required value={code} onChange={e => setCode(e.target.value)} /></label>
      {error && <div className="notice" role="alert">{error}</div>}
      <div style={{ display: 'flex', gap: 8 }}><button className="primary" type="submit" disabled={busy}>{off ? t('Switch off', 'إيقاف') : t('Get new codes', 'الحصول على رموز جديدة')}</button>
        <button type="button" className="refresh" onClick={back}>{t('Cancel', 'إلغاء')}</button></div>
    </form>;
  }

  return <div className="nuqati-account-card">
    {heading}
    {status.enabled
      ? <>
        <p><ShieldCheck size={16} aria-hidden="true" /> {t('On. Sign-in asks for a code from your authenticator app.', 'مفعّل. يطلب تسجيل الدخول رمزاً من تطبيق المصادقة.')}</p>
        <p><small>{t(`Recovery codes left: ${status.recovery_codes_remaining}`, `رموز الاسترداد المتبقية: ${status.recovery_codes_remaining}`)}</small></p>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="refresh" onClick={() => setView('change')}>{t('Change authenticator', 'تغيير تطبيق المصادقة')}</button>
          <button type="button" className="refresh" onClick={() => setView('codes')}>{t('New recovery codes', 'رموز استرداد جديدة')}</button>
          {!status.required && <button type="button" className="refresh" onClick={() => setView('off')}>{t('Switch off', 'إيقاف')}</button>}
        </div>
        {status.required && <p><small>{t('Your role requires it, so it cannot be switched off.', 'دورك يتطلبه، لذلك لا يمكن إيقافه.')}</small></p>}
      </>
      : <>
        <p>{t('Off. Adding a code from an authenticator app protects your account if your password is stolen.', 'متوقف. إضافة رمز من تطبيق مصادقة تحمي حسابك إذا سُرقت كلمة المرور.')}</p>
        <button type="button" className="primary" onClick={() => setView('setup')}>{t('Set up', 'إعداد')}</button>
      </>}
    {error && <div className="notice" role="alert">{error}</div>}
  </div>;
}

/** For a super admin on the user page: is two-step sign-in on for this person, and a reset button. */
export function TwoStepAdminReset({ lang, api, token, userId }: { lang: Lang; api: string; token: string; userId: number }) {
  const t = texts(lang);
  const [info, setInfo] = useState<{ available: boolean; enabled: boolean; required: boolean } | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  async function load() { try { setInfo(await call(api, token, `/api/v1/users/${userId}/mfa`, 'GET')); } catch (err) { setMessage(err instanceof Error ? err.message : String(err)); } }
  useEffect(() => { void load(); }, [userId]);
  async function reset() {
    if (!window.confirm(t('Remove this person\'s two-step sign-in and end their sessions? They will sign in with the password and set it up again.', 'إزالة تسجيل الدخول بخطوتين لهذا الشخص وإنهاء جلساته؟ سيسجل الدخول بكلمة المرور ثم يعدّه من جديد.'))) return;
    setBusy(true); setMessage('');
    try { await call(api, token, `/api/v1/users/${userId}/mfa/reset`, 'POST'); setMessage(t('Reset. Their sessions ended.', 'تمت إعادة التعيين وانتهت جلساته.')); await load(); }
    catch (err) { setMessage(err instanceof Error ? err.message : String(err)); } finally { setBusy(false); }
  }
  if (!info) return message ? <div className="nq-ve-info nq-ve-wide" role="alert">{message}</div> : null;
  if (!info.available) return <div className="nq-ve-info nq-ve-wide"><KeyRound size={17} />{t('Two-step sign-in is not switched on on this server.', 'تسجيل الدخول بخطوتين غير مفعل على هذا الخادم.')}</div>;
  return <div className="nq-ve-fields">
    <div className="nq-ve-info nq-ve-wide"><ShieldCheck size={17} />{info.enabled ? t('Two-step sign-in is ON for this person.', 'تسجيل الدخول بخطوتين مفعّل لهذا الشخص.') : t('Two-step sign-in is off for this person.', 'تسجيل الدخول بخطوتين متوقف لهذا الشخص.')}
      {info.required && !info.enabled ? ' ' + t('Their role requires it: they will be asked to set it up at the next sign-in.', 'دوره يتطلبه: سيُطلب منه إعداده عند تسجيل الدخول التالي.') : ''}</div>
    {info.enabled && <button type="button" className="nq-ve-cancel" disabled={busy} onClick={() => { void reset(); }}>{t('Reset two-step sign-in', 'إعادة تعيين تسجيل الدخول بخطوتين')}</button>}
    {message && <div className="nq-ve-info nq-ve-wide" role="status">{message}</div>}
  </div>;
}
