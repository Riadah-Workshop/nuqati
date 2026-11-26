import { useState, type FormEvent } from 'react';
import { TwoStepAdminReset } from './TwoStep';
import { ArrowLeft, ArrowRight, BadgeCheck, Building2, ClipboardList, IdCard, KeyRound, LockKeyhole, Mail, Save, ShieldCheck, UserCog, UserRound } from 'lucide-react';

export type EditableUser = {
  id: number;
  email: string;
  full_name: string;
  role: string;
  company_id: number | null;
  is_active: boolean;
};
export type UserUpdate = {
  full_name?: string;
  role?: string;
  company_id?: number | null;
  is_active?: boolean;
};
type Props = {
  user: EditableUser;
  companies: {id:number;name:string}[];
  currentUserId: number;
  lang: 'en' | 'ar';
  onClose: () => void;
  onSave: (changes:UserUpdate) => Promise<void>;
  /** With these two the page shows the two-step sign-in status and the reset button (super admin only; the server enforces it). */
  api?: string;
  token?: string;
};
const ROLES = ['super_admin', 'company_admin', 'fleet_manager', 'representative', 'driver', 'workshop_staff'] as const;
const ROLE_NAMES:Record<string,[string,string]> = {
  super_admin:['Super Admin','المدير العام'],
  company_admin:['Company Admin','مدير الشركة'],
  fleet_manager:['Fleet Manager','مدير الأسطول'],
  representative:['Representative','ممثل'],
  driver:['Driver','سائق'],
  workshop_staff:['Workshop Staff','موظف الورشة']
};

export default function UserEditPage({user,companies,currentUserId,lang,onClose,onSave,api,token}:Props){
  const ar=lang==='ar';
  const t=(en:string,arabic:string)=>ar?arabic:en;
  const [name,setName]=useState(user.full_name);
  const [role,setRole]=useState(user.role);
  const [companyId,setCompanyId]=useState(user.company_id===null?'':String(user.company_id));
  const [active,setActive]=useState(user.is_active);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const isSelf=user.id===currentUserId;
  const selectedCompany=companies.find(company=>String(company.id)===companyId)?.name;
  const companyRequired=role!=='super_admin';
  const nextCompany=companyRequired?(companyId?Number(companyId):null):null;
  const changed=name.trim()!==user.full_name||role!==user.role||nextCompany!==user.company_id||active!==user.is_active;
  const close=()=>{
    if(busy)return;
    if(changed&&!window.confirm(t('Discard unsaved user changes?','هل تريد تجاهل تغييرات المستخدم غير المحفوظة؟')))return;
    onClose();
  };
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    if(busy||!changed)return;
    setError('');
    if(name.trim().length<2||name.trim().length>160){
      setError(t('Full name must contain 2–160 characters.','يجب أن يتكون الاسم الكامل من 2 إلى 160 حرفاً.'));
      return;
    }
    if(companyRequired&&(!companyId||!companies.some(c=>c.id===nextCompany))){
      setError(t('Select a valid company for this role.','اختر شركة صحيحة لهذا الدور.'));
      return;
    }
    if(isSelf&&(role!=='super_admin'||!active)){
      setError(t('You cannot remove your own Super Admin access.','لا يمكنك إزالة صلاحية المدير العام من حسابك.'));
      return;
    }
    const changes:UserUpdate={};
    if(name.trim()!==user.full_name)changes.full_name=name.trim();
    if(role!==user.role)changes.role=role;
    if(nextCompany!==user.company_id)changes.company_id=nextCompany;
    if(active!==user.is_active)changes.is_active=active;
    setBusy(true);
    try{await onSave(changes);}
    catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setBusy(false);}
  }
  const roleName=(value:string)=>ROLE_NAMES[value]?.[ar?1:0]||value;
  return <section className="nq-vehicle-editor nq-entity-editor nq-user-editor" dir={ar?'rtl':'ltr'} aria-label={t('Edit user and access','تعديل المستخدم والصلاحيات')}>
    <div className="nq-ve-breadcrumb"><button type="button" className="nq-ve-back" onClick={close}>{ar?<ArrowRight size={16}/>:<ArrowLeft size={16}/>} {t('All users','كل المستخدمين')}</button><span>/</span><strong>{user.full_name}</strong></div>
    <form onSubmit={save}>
      <header className="nq-ve-header">
        <div className="nq-ve-header-title"><div className="nq-ve-title-icon"><UserCog size={25}/></div><div><span className="nq-ve-kicker">{t('ADMINISTRATION · USER ACCESS','الإدارة · صلاحيات المستخدم')}</span><h2>{t('Edit user','تعديل المستخدم')} <span>{user.full_name}</span></h2><p>{t('Update profile, role, company and access status in one place.','تعديل الاسم والدور والشركة وحالة الحساب في صفحة واحدة.')}</p></div></div>
        <div className="nq-ve-header-actions"><span className="nq-ve-availability"><BadgeCheck size={16}/>{active?t('Active account','حساب نشط'):t('Inactive / pending','غير نشط / بانتظار التفعيل')}</span><button type="button" className="nq-ve-cancel" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button><button type="submit" className="nq-ve-save" disabled={!changed||busy}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button></div>
      </header>
      <div className="nq-ve-workspace">
        <aside className="nq-ve-aside"><div className="nq-ve-preview"><div className="nq-ve-car"><UserRound size={54} strokeWidth={1.5}/></div><strong>{user.full_name}</strong><small>{t('User account','حساب المستخدم')} #{user.id}</small><div className="nq-ve-preview-company">{roleName(role)}</div></div>
          <nav className="nq-ve-sections" aria-label={t('User editor sections','أقسام تعديل المستخدم')}><a href="#nq-user-profile"><IdCard size={17}/>{t('Account details','بيانات الحساب')}</a><a href="#nq-user-access"><ShieldCheck size={17}/>{t('Role & company','الدور والشركة')}</a><a href="#nq-user-status"><KeyRound size={17}/>{t('Access status','حالة الوصول')}</a></nav>
          <div className="nq-ve-aside-tip"><LockKeyhole size={18}/><p>{t('Email changes and password recovery use separate verified security processes. Existing invitation and account controls remain available in the users list.','تغيير البريد واستعادة كلمة المرور تتم عبر إجراءات أمان مستقلة. تبقى الدعوات وإدارة الحسابات متاحة من قائمة المستخدمين.')}</p></div>
        </aside>
        <div className="nq-ve-main">
          <section className="nq-ve-section" id="nq-user-profile"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><ClipboardList size={19}/></span><div><h3>{t('Account details','بيانات الحساب')}</h3><p>{t('User identity and registered sign-in address','هوية المستخدم وبريد تسجيل الدخول')}</p></div></div>
            <div className="nq-ve-fields"><label>{t('Full name','الاسم الكامل')} <span className="nq-ve-required">*</span><input autoFocus required minLength={2} maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label><label>{t('User ID','معرّف المستخدم')}<input value={user.id} readOnly/></label>
              <label>{t('Account email','البريد الإلكتروني للحساب')}<input type="email" value={user.email} readOnly/></label><div className="nq-ve-info"><Mail size={17}/>{t('Email is read-only here. Use the verified email-change flow for your own account.','البريد للعرض فقط. استخدم إجراء تغيير البريد الموثق لحسابك الشخصي.')}</div></div>
          </section>
          <section className="nq-ve-section" id="nq-user-access"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><Building2 size={19}/></span><div><h3>{t('Role & company assignment','الدور وربط الشركة')}</h3><p>{t('Select the user’s permission role and owning company','حدد صلاحيات المستخدم والشركة المرتبط بها')}</p></div></div>
            <div className="nq-ve-fields"><label>{t('Access role','الدور والصلاحية')} <span className="nq-ve-required">*</span><select required value={role} onChange={e=>setRole(e.target.value)} disabled={isSelf}>{ROLES.map(r=><option key={r} value={r}>{roleName(r)}</option>)}</select>{isSelf&&<small className="nq-entity-hint">{t('Your own Super Admin role cannot be changed.','لا يمكن تغيير صلاحية المدير العام لحسابك.')}</small>}</label>
              {companyRequired?<label>{t('Assigned company','الشركة المرتبطة')} <span className="nq-ve-required">*</span><select required value={companyId} onChange={e=>setCompanyId(e.target.value)}><option value="">{t('Choose company','اختر الشركة')}</option>{companies.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></label>:<label>{t('Assigned company','الشركة المرتبطة')}<input readOnly value={t('Platform-wide · all companies','النظام بالكامل · كل الشركات')}/></label>}
              <div className="nq-ve-info nq-ve-wide"><ShieldCheck size={17}/>{role==='super_admin'?t('Super Admin access spans the platform. Super Admin accounts cannot be assigned to a client company.','صلاحية المدير العام تشمل المنصة كاملة، ولا يمكن ربط هذا الدور بشركة عميلة.'):t(`The selected role applies to ${selectedCompany||'the assigned company'} according to existing server access rules.`,`يسري الدور المختار على ${selectedCompany||'الشركة المحددة'} وفق ضوابط الصلاحيات المعتمدة في الخادم.`)}</div></div>
          </section>
          <section className="nq-ve-section" id="nq-user-status"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><KeyRound size={19}/></span><div><h3>{t('Access status','حالة الوصول')}</h3><p>{t('Manage whether the account can sign in','تحديد إمكانية تسجيل دخول المستخدم')}</p></div></div>
            <div className="nq-ve-fields"><label>{t('Account status','حالة الحساب')}<select value={active?'active':'inactive'} onChange={e=>setActive(e.target.value==='active')} disabled={isSelf}><option value="active">{t('Active','نشط')}</option><option value="inactive">{t('Inactive / pending','غير نشط / بانتظار التفعيل')}</option></select></label><div className="nq-ve-info"><LockKeyhole size={17}/>{t('Activating an account does not set or change a password. Invitations, reminders and password resets stay separate.','تفعيل الحساب لا يُنشئ كلمة مرور ولا يغيرها؛ تبقى الدعوات والتذكيرات وإعادة التعيين عمليات منفصلة.')}</div></div>
          </section>
          {api&&token&&!isSelf&&user.role!=='driver'&&<section className="nq-ve-section" id="nq-user-mfa"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><ShieldCheck size={19}/></span><div><h3>{t('Two-step sign-in','تسجيل الدخول بخطوتين')}</h3><p>{t('Authenticator-app code in addition to the password. Reset it if this person lost their phone and recovery codes.','رمز من تطبيق المصادقة إضافة إلى كلمة المرور. أعد تعيينه إذا فقد هذا الشخص هاتفه ورموز الاسترداد.')}</p></div></div>
            <TwoStepAdminReset lang={lang} api={api} token={token} userId={user.id}/>
          </section>}
          {error&&<div role="alert" className="nq-ve-error">{error}</div>}
          <footer className="nq-ve-footer"><span>{changed?t('Unsaved changes','تغييرات غير محفوظة'):t('All fields are up to date','البيانات محدثة')}</span><div><button type="button" className="nq-ve-cancel" disabled={busy} onClick={close}>{t('Cancel','إلغاء')}</button><button type="submit" className="nq-ve-save" disabled={!changed||busy}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button></div></footer>
        </div>
      </div>
    </form>
  </section>;
}
