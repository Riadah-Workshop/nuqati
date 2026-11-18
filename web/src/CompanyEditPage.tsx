import { useState, type FormEvent, type ChangeEvent } from 'react';
import { ArrowLeft, ArrowRight, BadgeCheck, Building2, ClipboardList, ImagePlus, Save, ShieldCheck, Users, CarFront } from 'lucide-react';

export type EditableCompany = {id:number; name:string};
export type CompanyUpdate = {name:string;logo_data?:string};
type Props = {
  company:EditableCompany;
  initialLogo:string;
  driverCount:number;
  vehicleCount:number;
  userCount:number;
  lang:'en'|'ar';
  onClose:()=>void;
  onSave:(changes:CompanyUpdate)=>Promise<void>;
};

export default function CompanyEditPage({company,initialLogo,driverCount,vehicleCount,userCount,lang,onClose,onSave}:Props){
  const ar=lang==='ar';
  const t=(en:string,arabic:string)=>ar?arabic:en;
  const [name,setName]=useState(company.name);
  const [logo,setLogo]=useState(initialLogo);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const changed=name.trim()!==company.name||logo!==initialLogo;
  function close(){if(busy)return;if(changed&&!window.confirm(t('Discard unsaved company changes?','تجاهل التغييرات غير المحفوظة على الشركة؟')))return;onClose();}
  function changeLogo(e:ChangeEvent<HTMLInputElement>){
    const file=e.target.files?.[0];if(!file)return;
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>220000){
      setError(t('Choose a PNG, JPEG or WebP image not exceeding 220 KB.','اختر صورة PNG أو JPEG أو WebP بحجم لا يتجاوز 220 كيلوبايت.'));e.target.value='';return;
    }
    const reader=new FileReader();reader.onload=()=>{setLogo(String(reader.result||''));setError('');};reader.onerror=()=>setError(t('Could not read the logo.','تعذرت قراءة الشعار.'));reader.readAsDataURL(file);
    e.target.value='';
  }
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();if(!changed||busy)return;setError('');
    if(name.trim().length<2||name.trim().length>160){setError(t('Company name must contain 2–160 characters.','اسم الشركة يجب أن يكون بين حرفين و160 حرفاً.'));return;}
    const changes:CompanyUpdate={name:name.trim()};
    if(logo!==initialLogo)changes.logo_data=logo;
    setBusy(true);
    try{await onSave(changes);}catch(err){setError(err instanceof Error?err.message:String(err));}finally{setBusy(false);}
  }
  return <section className="nq-vehicle-editor nq-entity-editor" dir={ar?'rtl':'ltr'} aria-label={t('Edit company','تعديل الشركة')}>
    <div className="nq-ve-breadcrumb"><button type="button" className="nq-ve-back" onClick={close}>{ar?<ArrowRight size={16}/>:<ArrowLeft size={16}/>} {t('All companies','كل الشركات')}</button><span>/</span><strong>{company.name}</strong></div>
    <form onSubmit={save}>
      <header className="nq-ve-header"><div className="nq-ve-header-title"><div className="nq-ve-title-icon"><Building2 size={25}/></div><div><span className="nq-ve-kicker">{t('FLEET MANAGEMENT · COMPANY PROFILE','إدارة الأسطول · ملف الشركة')}</span><h2>{t('Edit company','تعديل الشركة')} <span>{company.name}</span></h2><p>{t('Company details and driver-app logo in one place.','بيانات الشركة وشعار تطبيق السائق في صفحة واحدة.')}</p></div></div><div className="nq-ve-header-actions"><span className="nq-ve-availability"><BadgeCheck size={16}/>{t('Registered','مسجلة')}</span><button className="nq-ve-cancel" type="button" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button><button type="submit" className="nq-ve-save" disabled={!changed||busy}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button></div></header>
      <div className="nq-ve-workspace"><aside className="nq-ve-aside"><div className="nq-ve-preview"><div className="nq-ve-car">{logo?<img className="nq-entity-avatar" src={logo} alt={t('Company logo','شعار الشركة')}/>:<Building2 size={54} strokeWidth={1.5}/>}</div><strong>{company.name}</strong><small>{t('Company','شركة')} #{company.id}</small><div className="nq-ve-preview-company">{t('Nuqati client fleet','أسطول عميل نقاطي')}</div></div><nav className="nq-ve-sections"><a href="#nq-company-details"><ClipboardList size={17}/>{t('Company details','بيانات الشركة')}</a><a href="#nq-company-logo"><ImagePlus size={17}/>{t('Driver-app logo','شعار تطبيق السائق')}</a><a href="#nq-company-fleet"><Users size={17}/>{t('Fleet summary','ملخص الأسطول')}</a></nav><div className="nq-ve-aside-tip"><ShieldCheck size={18}/><p>{t('Company ID and linked fleet ownership cannot be changed here.','لا يمكن تغيير معرف الشركة أو ملكية بيانات أسطولها من هنا.')}</p></div></aside>
        <div className="nq-ve-main"><section className="nq-ve-section" id="nq-company-details"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><Building2 size={19}/></span><div><h3>{t('Company details','بيانات الشركة')}</h3><p>{t('Main company identification','بيانات تعريف الشركة الأساسية')}</p></div></div><div className="nq-ve-fields"><label>{t('Company name','اسم الشركة')} <span className="nq-ve-required">*</span><input autoFocus required minLength={2} maxLength={160} value={name} onChange={e=>setName(e.target.value)}/></label><label>{t('Company ID','معرف الشركة')}<input value={company.id} readOnly/></label></div></section>
          <section className="nq-ve-section" id="nq-company-logo"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><ImagePlus size={19}/></span><div><h3>{t('Android driver-app logo','شعار تطبيق السائق على أندرويد')}</h3><p>{t('Used for company branding in the mobile driver app','يستخدم لهوية الشركة داخل تطبيق السائق')}</p></div></div><div className="nq-ve-fields"><label>{t('Upload or replace company logo','رفع أو استبدال شعار الشركة')}<input type="file" accept="image/png,image/jpeg,image/webp" onChange={changeLogo}/><small className="nq-entity-hint">{t('PNG, JPEG or WebP · maximum 220 KB','PNG أو JPEG أو WebP · الحد الأقصى 220 كيلوبايت')}</small></label><div className="nq-entity-logo-preview"><div>{logo?<img src={logo} alt={t('Selected logo preview','معاينة الشعار المختار')}/>:<ImagePlus size={36}/>}</div><span>{logo?t('Selected company logo','الشعار المختار'):t('No logo uploaded','لم يتم رفع شعار')}</span>{logo&&<button type="button" className="nq-ve-cancel" onClick={()=>setLogo('')}>{t('Remove logo','إزالة الشعار')}</button>}</div></div></section>
          <section className="nq-ve-section" id="nq-company-fleet"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><CarFront size={19}/></span><div><h3>{t('Company fleet summary','ملخص أسطول الشركة')}</h3><p>{t('Read-only counts; manage these records in their dedicated pages','الأعداد للعرض فقط؛ تُدار السجلات من صفحاتها الخاصة')}</p></div></div><div className="nq-entity-stats"><div><Users size={18}/><strong>{driverCount}</strong><span>{t('Drivers','السائقون')}</span></div><div><CarFront size={18}/><strong>{vehicleCount}</strong><span>{t('Vehicles','السيارات')}</span></div><div><ShieldCheck size={18}/><strong>{userCount}</strong><span>{t('User accounts','حسابات المستخدمين')}</span></div></div></section>
          {error&&<div role="alert" className="nq-ve-error">{error}</div>}
          <footer className="nq-ve-footer"><span>{changed?t('Unsaved changes','تغييرات غير محفوظة'):t('All fields are up to date','البيانات محدثة')}</span><div><button type="button" className="nq-ve-cancel" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button><button type="submit" className="nq-ve-save" disabled={!changed||busy}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button></div></footer>
        </div></div>
    </form>
  </section>;
}
