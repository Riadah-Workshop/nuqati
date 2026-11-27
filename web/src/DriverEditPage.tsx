import { useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, BadgeCheck, CarFront, Check, ClipboardList, Copy, IdCard, KeyRound, LogOut, MapPin, Save, ShieldCheck, Smartphone, UserRound, Users } from 'lucide-react';

export type EditableDriver = {id:number;company_id:number;full_name:string;phone:string;status:string};
export type DriverDetails = {id_number:string;site_name:string;vehicle_id:number|null};
export type DriverDeviceSession = {linked:boolean;active:boolean;since:string|null;last_login_at:string|null};
export type DriverPasswordResult = {status:string;released_device:boolean;temporary_password?:string};
export type DriverUpdate = {full_name?:string;phone?:string;status?:string;id_number?:string;site_name?:string;vehicle_id?:number|null};
type Props = {
  driver:EditableDriver; details:DriverDetails; companyName:string;
  vehicles:{id:number;company_id:number;plate_number:string;make_model:string;assigned_driver_id?:number|null}[];
  lastLogin?:string; lang:'en'|'ar';onClose:()=>void;onSave:(changes:DriverUpdate)=>Promise<void>;
  // Sign-in controls: only passed for super admins and company admins (the server enforces the same rule).
  canManageAccess?:boolean; deviceSession?:DriverDeviceSession|null;
  onReleaseDevice?:()=>Promise<void>; onResetPassword?:(options:{newPassword?:string;releaseDevice:boolean})=>Promise<DriverPasswordResult>;
};
export default function DriverEditPage({driver,details,companyName,vehicles,lastLogin,lang,onClose,onSave,canManageAccess,deviceSession,onReleaseDevice,onResetPassword}:Props){
  const ar=lang==='ar';const t=(en:string,arabic:string)=>ar?arabic:en;
  const [name,setName]=useState(driver.full_name);
  const [phone,setPhone]=useState(driver.phone);
  const [status,setStatus]=useState(driver.status);
  const [idNumber,setIdNumber]=useState(details.id_number);
  const [site,setSite]=useState(details.site_name);
  const [vehicleId,setVehicleId]=useState(details.vehicle_id==null?'':String(details.vehicle_id));
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const currentVehicle=details.vehicle_id==null?'':String(details.vehicle_id);
  const selectedVehicle=vehicleId===''?null:Number(vehicleId);
  const changed=name.trim()!==driver.full_name||phone.trim()!==driver.phone||status!==driver.status||idNumber.trim()!==details.id_number||site.trim()!==details.site_name||vehicleId!==currentVehicle;
  const eligibleVehicles=vehicles.filter(v=>v.company_id===driver.company_id&&(!v.assigned_driver_id||v.assigned_driver_id===driver.id||String(v.id)===currentVehicle));
  const [accessBusy,setAccessBusy]=useState(false);const [accessError,setAccessError]=useState('');const [accessNote,setAccessNote]=useState('');
  const [resetOpen,setResetOpen]=useState(false);const [resetMode,setResetMode]=useState<'generate'|'type'>('generate');
  const [typedPassword,setTypedPassword]=useState('');const [alsoRelease,setAlsoRelease]=useState(true);
  const [issued,setIssued]=useState('');const [copied,setCopied]=useState(false);
  const sessionLinked=Boolean(deviceSession?.linked);const sessionActive=Boolean(deviceSession?.active);
  const fmt=(value:string)=>new Date(value).toLocaleString(ar?'ar-SA':'en-GB');
  const sessionText=!deviceSession?t('Checking the sign-in status…','جارٍ فحص حالة الدخول…')
    :!deviceSession.linked?t('This driver has no app login yet.','لا يوجد حساب دخول للتطبيق لهذا السائق بعد.')
    :deviceSession.active?t('A phone is signed in','هاتف مسجّل الدخول حالياً')+(deviceSession.since?' · '+t('since','منذ')+' '+fmt(deviceSession.since):'')
    :t('No phone is signed in. The driver can sign in on any phone.','لا يوجد هاتف مسجّل الدخول. يستطيع السائق الدخول من أي هاتف.');
  async function releasePhone(){
    if(!onReleaseDevice||accessBusy)return;
    if(!window.confirm(t("Sign out this driver's phone? The driver is signed out of the app and can sign in again on any phone.",'تسجيل خروج هاتف السائق؟ سيتم إنهاء جلسته في التطبيق ويمكنه تسجيل الدخول من أي هاتف.')))return;
    setAccessBusy(true);setAccessError('');setAccessNote('');
    try{await onReleaseDevice();setAccessNote(t('Done. The driver can now sign in on a new or reinstalled phone.','تم. يستطيع السائق الآن تسجيل الدخول من هاتف جديد أو بعد إعادة تثبيت التطبيق.'));}
    catch(err){setAccessError(err instanceof Error?err.message:String(err));}finally{setAccessBusy(false);}
  }
  async function resetPassword(){
    if(!onResetPassword||accessBusy)return;
    if(resetMode==='type'&&(typedPassword.length<12||typedPassword.length>128)){setAccessError(t('The password must be 12 to 128 characters.','يجب أن تكون كلمة المرور من 12 إلى 128 حرفاً.'));return;}
    if(!window.confirm(t("Set a new password for this driver? The driver's current sign-in ends immediately.",'تعيين كلمة مرور جديدة للسائق؟ ستنتهي جلسته الحالية فوراً.')))return;
    setAccessBusy(true);setAccessError('');setAccessNote('');setIssued('');setCopied(false);
    try{
      const result=await onResetPassword({newPassword:resetMode==='type'?typedPassword:undefined,releaseDevice:alsoRelease});
      setTypedPassword('');setResetOpen(false);
      if(result.temporary_password)setIssued(result.temporary_password);
      setAccessNote(result.temporary_password?t('New temporary password created. It is shown once, below.','تم إنشاء كلمة مرور مؤقتة جديدة. تظهر مرة واحدة فقط أدناه.'):t('Password changed. Tell the driver the new password privately.','تم تغيير كلمة المرور. أبلغ السائق بها بشكل خاص.'));
    }catch(err){setAccessError(err instanceof Error?err.message:String(err));}finally{setAccessBusy(false);}
  }
  async function copyIssued(){try{await navigator.clipboard.writeText(issued);setCopied(true);}catch{setCopied(false);}}
  function close(){if(busy)return;if(changed&&!window.confirm(t('Discard unsaved driver changes?','تجاهل التغييرات غير المحفوظة على السائق؟')))return;onClose();}
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();if(!changed||busy)return;setError('');
    if(name.trim().length<2||name.trim().length>160||phone.trim().length>40||(phone.trim()!==driver.phone&&!phone.trim())){
      setError(t('Enter a valid name (2–160 characters) and mobile number.','أدخل اسماً صحيحاً (2–160 حرفاً) ورقم جوال.'));return;
    }
    if((idNumber.trim()!==details.id_number||site.trim()!==details.site_name)&&(!idNumber.trim()||!site.trim())){
      setError(t('ID/Iqama and site must both be filled to change identification details.','لتعديل بيانات الهوية يجب إدخال رقم الهوية والموقع معاً.'));return;
    }
    const changes:DriverUpdate={};
    if(name.trim()!==driver.full_name)changes.full_name=name.trim();
    if(phone.trim()!==driver.phone)changes.phone=phone.trim();
    if(status!==driver.status)changes.status=status;
    if(idNumber.trim()!==details.id_number)changes.id_number=idNumber.trim();
    if(site.trim()!==details.site_name)changes.site_name=site.trim();
    if(selectedVehicle!==details.vehicle_id)changes.vehicle_id=selectedVehicle;
    setBusy(true);
    try{await onSave(changes);}catch(err){setError(err instanceof Error?err.message:String(err));}finally{setBusy(false);}
  }
  return <section className="nq-vehicle-editor nq-entity-editor" dir={ar?'rtl':'ltr'} aria-label={t('Edit driver','تعديل السائق')}>
    <div className="nq-ve-breadcrumb"><button type="button" className="nq-ve-back" onClick={close}>{ar?<ArrowRight size={16}/>:<ArrowLeft size={16}/>} {t('All drivers','كل السائقين')}</button><span>/</span><strong>{driver.full_name}</strong></div>
    <form onSubmit={save}><header className="nq-ve-header"><div className="nq-ve-header-title"><div className="nq-ve-title-icon"><UserRound size={25}/></div><div><span className="nq-ve-kicker">{t('FLEET MANAGEMENT · DRIVER PROFILE','إدارة الأسطول · ملف السائق')}</span><h2>{t('Edit driver','تعديل السائق')} <span>{driver.full_name}</span></h2><p>{t('Update driver profile, status and vehicle assignment together.','تعديل بيانات السائق وحالته وتعيين المركبة في مكان واحد.')}</p></div></div><div className="nq-ve-header-actions"><span className="nq-ve-availability"><BadgeCheck size={16}/>{t('Registered','مسجل')}</span><button type="button" className="nq-ve-cancel" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button><button type="submit" className="nq-ve-save" disabled={!changed||busy}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button></div></header>
      <div className="nq-ve-workspace"><aside className="nq-ve-aside"><div className="nq-ve-preview"><div className="nq-ve-car"><UserRound size={54} strokeWidth={1.5}/></div><strong>{driver.full_name}</strong><small>{t('Driver','سائق')} #{driver.id}</small><div className="nq-ve-preview-company">{companyName}</div></div><nav className="nq-ve-sections"><a href="#nq-driver-personal"><IdCard size={17}/>{t('Personal details','البيانات الشخصية')}</a><a href="#nq-driver-assignment"><CarFront size={17}/>{t('Vehicle assignment','تعيين المركبة')}</a><a href="#nq-driver-access"><ShieldCheck size={17}/>{t('Status & app activity','الحالة ونشاط التطبيق')}</a>{canManageAccess&&<a href="#nq-driver-signin"><Smartphone size={17}/>{t('Phone sign-in & password','دخول الهاتف وكلمة المرور')}</a>}</nav><div className="nq-ve-aside-tip"><ShieldCheck size={18}/><p>{t('Company transfer remains a separate protected workflow. Active handover rules are enforced when changing vehicles.','نقل الشركة عملية آمنة منفصلة؛ وتطبق قواعد تسليم المركبات عند تغيير التعيين.')}</p></div></aside>
      <div className="nq-ve-main"><section className="nq-ve-section" id="nq-driver-personal"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><ClipboardList size={19}/></span><div><h3>{t('Personal details','البيانات الشخصية')}</h3><p>{t('Driver identification and contact details','هوية السائق وبيانات التواصل')}</p></div></div><div className="nq-ve-fields"><label>{t('Full name','الاسم الكامل')} <span className="nq-ve-required">*</span><input autoFocus required minLength={2} maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label><label>{t('Mobile number','رقم الجوال')} <span className="nq-ve-required">*</span><input type="tel" required={Boolean(driver.phone)} maxLength={40} value={phone} onChange={e=>setPhone(e.target.value)} placeholder="+9665XXXXXXXX"/></label><label>{t('ID / Iqama number','رقم الهوية / الإقامة')}<input maxLength={40} value={idNumber} onChange={e=>setIdNumber(e.target.value)}/></label><label>{t('Site / Branch','الموقع / الفرع')}<input maxLength={160} value={site} onChange={e=>setSite(e.target.value)}/></label><label>{t('Company','الشركة')}<input readOnly value={companyName}/></label><label>{t('Driver ID','معرّف السائق')}<input readOnly value={driver.id}/></label></div></section>
        <section className="nq-ve-section" id="nq-driver-assignment"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><CarFront size={19}/></span><div><h3>{t('Vehicle assignment','تعيين المركبة')}</h3><p>{t('Assign an available vehicle within the same company','اختر مركبة متاحة ضمن الشركة نفسها')}</p></div></div><div className="nq-ve-fields"><label>{t('Assigned vehicle','المركبة المخصصة')}<select value={vehicleId} onChange={e=>setVehicleId(e.target.value)}><option value="">{t('Unassigned — no vehicle','غير معيّن — بدون مركبة')}</option>{eligibleVehicles.map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}{vehicleId!==''&&!eligibleVehicles.some(v=>String(v.id)===vehicleId)&&<option value={vehicleId}>{t('Current vehicle','المركبة الحالية')} #{vehicleId}</option>}</select></label><div className="nq-ve-info"><MapPin size={17}/>{t('Changing an active handover assignment may require a documented online return. Existing vehicle-assignment safeguards are preserved.','قد يتطلب تغيير مركبة مسلّمة إرجاعاً إلكترونياً موثقاً. تبقى ضوابط تعيين المركبات مفعّلة.')}</div></div></section>
        <section className="nq-ve-section" id="nq-driver-access"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><Users size={19}/></span><div><h3>{t('Status & app activity','الحالة ونشاط التطبيق')}</h3><p>{t('Driver record status and latest confirmed app login','حالة السائق وآخر تسجيل دخول مؤكد للتطبيق')}</p></div></div><div className="nq-ve-fields"><label>{t('Driver status','حالة السائق')}<select value={status} onChange={e=>setStatus(e.target.value)}><option value="active">{t('Active','نشط')}</option><option value="inactive">{t('Inactive','غير نشط')}</option><option value="archived">{t('Archived','مؤرشف')}</option></select></label><label>{t('Last app login acknowledgment (UTC)','آخر تأكيد دخول للتطبيق (UTC)')}<input readOnly value={lastLogin?new Date(lastLogin).toLocaleString(ar?'ar-SA':'en-GB'):(t('Never acknowledged','لم يتم تأكيد الدخول'))}/></label></div></section>
        {canManageAccess&&<section className="nq-ve-section" id="nq-driver-signin"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><Smartphone size={19}/></span><div><h3>{t('Phone sign-in & password','دخول الهاتف وكلمة المرور')}</h3><p>{t("Free the driver's phone after a lost phone or a reinstall, or set a new password.",'حرّر هاتف السائق بعد فقدانه أو إعادة تثبيت التطبيق، أو عيّن كلمة مرور جديدة.')}</p></div></div>
          <div className="nq-da-status" role="status"><span className={`nq-da-dot${sessionActive?' on':''}`} aria-hidden="true"/><span>{sessionText}</span></div>
          <div className="nq-da-actions">
            <button type="button" className="nq-ve-cancel nq-da-danger" disabled={!sessionActive||accessBusy} onClick={releasePhone}><LogOut size={16}/>{t("Sign out driver's phone",'تسجيل خروج هاتف السائق')}</button>
            <button type="button" className="nq-ve-cancel" disabled={!sessionLinked||accessBusy} aria-expanded={resetOpen} onClick={()=>{setResetOpen(open=>!open);setAccessError('');}}><KeyRound size={16}/>{t('Reset password','إعادة تعيين كلمة المرور')}</button>
          </div>
          {resetOpen&&<div className="nq-da-panel">
            <label className="nq-da-choice"><input type="radio" name="nq-da-mode" checked={resetMode==='generate'} onChange={()=>setResetMode('generate')}/><span><strong>{t('Create a temporary password (recommended)','إنشاء كلمة مرور مؤقتة (موصى به)')}</strong><small>{t('You see it once and give it to the driver, who then changes it in the app.','تظهر لك مرة واحدة وتسلّمها للسائق ليغيّرها من التطبيق.')}</small></span></label>
            <label className="nq-da-choice"><input type="radio" name="nq-da-mode" checked={resetMode==='type'} onChange={()=>setResetMode('type')}/><span><strong>{t('I will type a password','سأكتب كلمة المرور بنفسي')}</strong><small>{t('At least 12 characters.','12 حرفاً على الأقل.')}</small></span></label>
            {resetMode==='type'&&<div className="nq-ve-fields nq-da-one"><label>{t('New password','كلمة المرور الجديدة')}<input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={typedPassword} onChange={e=>setTypedPassword(e.target.value)} onKeyDown={e=>{if(e.key==='Enter')e.preventDefault();}}/></label></div>}
            <label className="nq-da-choice"><input type="checkbox" checked={alsoRelease} onChange={e=>setAlsoRelease(e.target.checked)}/><span><strong>{t("Also sign out the driver's phone",'تسجيل خروج هاتف السائق أيضاً')}</strong><small>{t('Needed when the phone was lost or the app was reinstalled.','مطلوب عند فقدان الهاتف أو إعادة تثبيت التطبيق.')}</small></span></label>
            <div><button type="button" className="nq-ve-save" disabled={accessBusy} onClick={resetPassword}><KeyRound size={16}/>{accessBusy?t('Working…','جارٍ التنفيذ…'):t('Set new password','تعيين كلمة المرور الجديدة')}</button></div>
          </div>}
          {issued&&<div className="nq-da-secret" role="status"><div><small>{t('Temporary password · shown only once','كلمة المرور المؤقتة · تظهر مرة واحدة فقط')}</small><code>{issued}</code></div><button type="button" className="nq-ve-cancel" onClick={copyIssued}>{copied?<Check size={16}/>:<Copy size={16}/>}{copied?t('Copied','تم النسخ'):t('Copy','نسخ')}</button><button type="button" className="nq-ve-cancel" onClick={()=>{setIssued('');setCopied(false);}}>{t('Hide','إخفاء')}</button><p>{t('Give it to the driver privately (a call or in person), not in a group chat.','سلّمها للسائق بشكل خاص (اتصال أو مباشرة) وليس في مجموعة محادثة.')}</p></div>}
          {accessNote&&<div className="nq-da-ok" role="status">{accessNote}</div>}
          {accessError&&<div role="alert" className="nq-ve-error">{accessError}</div>}
        </section>}
        {error&&<div role="alert" className="nq-ve-error">{error}</div>}
        <footer className="nq-ve-footer"><span>{changed?t('Unsaved changes','تغييرات غير محفوظة'):t('All fields are up to date','البيانات محدثة')}</span><div><button type="button" className="nq-ve-cancel" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button><button type="submit" className="nq-ve-save" disabled={!changed||busy}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button></div></footer>
      </div></div>
    </form>
  </section>;
}
