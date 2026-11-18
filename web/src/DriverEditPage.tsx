import { useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, BadgeCheck, CarFront, ClipboardList, IdCard, MapPin, Save, ShieldCheck, UserRound, Users } from 'lucide-react';

export type EditableDriver = {id:number;company_id:number;full_name:string;phone:string;status:string};
export type DriverDetails = {id_number:string;site_name:string;vehicle_id:number|null};
export type DriverUpdate = {full_name?:string;phone?:string;status?:string;id_number?:string;site_name?:string;vehicle_id?:number|null};
type Props = {
  driver:EditableDriver; details:DriverDetails; companyName:string;
  vehicles:{id:number;company_id:number;plate_number:string;make_model:string;assigned_driver_id?:number|null}[];
  lastLogin?:string; lang:'en'|'ar';onClose:()=>void;onSave:(changes:DriverUpdate)=>Promise<void>;
};
export default function DriverEditPage({driver,details,companyName,vehicles,lastLogin,lang,onClose,onSave}:Props){
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
      <div className="nq-ve-workspace"><aside className="nq-ve-aside"><div className="nq-ve-preview"><div className="nq-ve-car"><UserRound size={54} strokeWidth={1.5}/></div><strong>{driver.full_name}</strong><small>{t('Driver','سائق')} #{driver.id}</small><div className="nq-ve-preview-company">{companyName}</div></div><nav className="nq-ve-sections"><a href="#nq-driver-personal"><IdCard size={17}/>{t('Personal details','البيانات الشخصية')}</a><a href="#nq-driver-assignment"><CarFront size={17}/>{t('Vehicle assignment','تعيين المركبة')}</a><a href="#nq-driver-access"><ShieldCheck size={17}/>{t('Status & app activity','الحالة ونشاط التطبيق')}</a></nav><div className="nq-ve-aside-tip"><ShieldCheck size={18}/><p>{t('Company transfer and password resets remain separate protected workflows. Active handover rules are enforced when changing vehicles.','نقل الشركة وإعادة تعيين كلمة المرور عمليات آمنة منفصلة؛ وتطبق قواعد تسليم المركبات عند تغيير التعيين.')}</p></div></aside>
      <div className="nq-ve-main"><section className="nq-ve-section" id="nq-driver-personal"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><ClipboardList size={19}/></span><div><h3>{t('Personal details','البيانات الشخصية')}</h3><p>{t('Driver identification and contact details','هوية السائق وبيانات التواصل')}</p></div></div><div className="nq-ve-fields"><label>{t('Full name','الاسم الكامل')} <span className="nq-ve-required">*</span><input autoFocus required minLength={2} maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label><label>{t('Mobile number','رقم الجوال')} <span className="nq-ve-required">*</span><input type="tel" required={Boolean(driver.phone)} maxLength={40} value={phone} onChange={e=>setPhone(e.target.value)} placeholder="+9665XXXXXXXX"/></label><label>{t('ID / Iqama number','رقم الهوية / الإقامة')}<input maxLength={40} value={idNumber} onChange={e=>setIdNumber(e.target.value)}/></label><label>{t('Site / Branch','الموقع / الفرع')}<input maxLength={160} value={site} onChange={e=>setSite(e.target.value)}/></label><label>{t('Company','الشركة')}<input readOnly value={companyName}/></label><label>{t('Driver ID','معرّف السائق')}<input readOnly value={driver.id}/></label></div></section>
        <section className="nq-ve-section" id="nq-driver-assignment"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><CarFront size={19}/></span><div><h3>{t('Vehicle assignment','تعيين المركبة')}</h3><p>{t('Assign an available vehicle within the same company','اختر مركبة متاحة ضمن الشركة نفسها')}</p></div></div><div className="nq-ve-fields"><label>{t('Assigned vehicle','المركبة المخصصة')}<select value={vehicleId} onChange={e=>setVehicleId(e.target.value)}><option value="">{t('Unassigned — no vehicle','غير معيّن — بدون مركبة')}</option>{eligibleVehicles.map(v=><option key={v.id} value={v.id}>{v.plate_number} — {v.make_model}</option>)}{vehicleId!==''&&!eligibleVehicles.some(v=>String(v.id)===vehicleId)&&<option value={vehicleId}>{t('Current vehicle','المركبة الحالية')} #{vehicleId}</option>}</select></label><div className="nq-ve-info"><MapPin size={17}/>{t('Changing an active handover assignment may require a documented online return. Existing vehicle-assignment safeguards are preserved.','قد يتطلب تغيير مركبة مسلّمة إرجاعاً إلكترونياً موثقاً. تبقى ضوابط تعيين المركبات مفعّلة.')}</div></div></section>
        <section className="nq-ve-section" id="nq-driver-access"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><Users size={19}/></span><div><h3>{t('Status & app activity','الحالة ونشاط التطبيق')}</h3><p>{t('Driver record status and latest confirmed app login','حالة السائق وآخر تسجيل دخول مؤكد للتطبيق')}</p></div></div><div className="nq-ve-fields"><label>{t('Driver status','حالة السائق')}<select value={status} onChange={e=>setStatus(e.target.value)}><option value="active">{t('Active','نشط')}</option><option value="inactive">{t('Inactive','غير نشط')}</option><option value="archived">{t('Archived','مؤرشف')}</option></select></label><label>{t('Last app login acknowledgment (UTC)','آخر تأكيد دخول للتطبيق (UTC)')}<input readOnly value={lastLogin?new Date(lastLogin).toLocaleString(ar?'ar-SA':'en-GB'):(t('Never acknowledged','لم يتم تأكيد الدخول'))}/></label></div></section>
        {error&&<div role="alert" className="nq-ve-error">{error}</div>}
        <footer className="nq-ve-footer"><span>{changed?t('Unsaved changes','تغييرات غير محفوظة'):t('All fields are up to date','البيانات محدثة')}</span><div><button type="button" className="nq-ve-cancel" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button><button type="submit" className="nq-ve-save" disabled={!changed||busy}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button></div></footer>
      </div></div>
    </form>
  </section>;
}
