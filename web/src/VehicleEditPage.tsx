import { useState, type FormEvent } from 'react';
import { ArrowLeft, ArrowRight, BadgeCheck, CarFront, ClipboardList, Gauge, Save, UserRound, Wrench } from 'lucide-react';

export type EditableVehicle = {
  id:number;
  company_id:number;
  plate_number:string;
  make_model:string;
  year:number|null;
  door_number:string|null;
  odometer_km:number|null;
  assigned_driver_id?:number|null;
};
export type VehicleDriverOption = {id:number;company_id:number;full_name:string};
export type VehicleUpdate = {
  plate_number?:string;
  make_model?:string;
  year?:number|null;
  door_number?:string|null;
  assigned_driver_id?:number|null;
  odometer_correction_km?:number;
  odometer_correction_reason?:string;
};

type Props = {
  vehicle:EditableVehicle;
  companyName:string;
  drivers:VehicleDriverOption[];
  vehicles:EditableVehicle[];
  canEdit:boolean;
  canCorrectOdometer:boolean;
  lang:'en'|'ar';
  onClose:()=>void;
  onSave:(changes:VehicleUpdate)=>Promise<void>;
};

/** One edit surface; all vehicle edits are submitted through a single Save action. */
export default function VehicleEditPage({vehicle,companyName,drivers,vehicles,canEdit,canCorrectOdometer,lang,onClose,onSave}:Props){
  const ar=lang==='ar';
  const [plate,setPlate]=useState(vehicle.plate_number);
  const [model,setModel]=useState(vehicle.make_model);
  const [year,setYear]=useState(vehicle.year===null?'':String(vehicle.year));
  const [door,setDoor]=useState(vehicle.door_number||'');
  const [driver,setDriver]=useState(vehicle.assigned_driver_id==null?'':String(vehicle.assigned_driver_id));
  const [odometer,setOdometer]=useState(vehicle.odometer_km==null?'':String(vehicle.odometer_km));
  const [correctionReason,setCorrectionReason]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');

  const updatedPlate=plate.trim();
  const updatedModel=model.trim();
  const updatedDoor=door.trim()||null;
  const updatedYear=year===''?null:Number(year);
  const updatedDriver=driver===''?null:Number(driver);
  const readingChanged=canCorrectOdometer&&odometer!==''&&Number(odometer)!==vehicle.odometer_km;
  const hasChanges=updatedPlate!==vehicle.plate_number||updatedModel!==vehicle.make_model||updatedYear!==vehicle.year||
    updatedDoor!==(vehicle.door_number||null)||updatedDriver!==(vehicle.assigned_driver_id??null)||readingChanged;
  const assigned=drivers.find(d=>d.id===vehicle.assigned_driver_id);
  const eligibleDrivers=drivers.filter(d=>d.company_id===vehicle.company_id&&
    (d.id===vehicle.assigned_driver_id||!vehicles.some(v=>v.id!==vehicle.id&&v.assigned_driver_id===d.id)));
  const t=(en:string,arabic:string)=>ar?arabic:en;

  function close(){
    if(busy)return;
    if(hasChanges&&!window.confirm(t('Discard unsaved vehicle changes?','تجاهل التغييرات غير المحفوظة على المركبة؟')))return;
    onClose();
  }
  async function save(e:FormEvent<HTMLFormElement>){
    e.preventDefault();
    if(!canEdit||busy||!hasChanges)return;
    setError('');
    if(!updatedPlate||!updatedModel){setError(t('Plate number and make/model are required.','رقم اللوحة والماركة والموديل حقول مطلوبة.'));return;}
    if(year!==''&&(!Number.isInteger(updatedYear)||updatedYear===null||updatedYear<1900||updatedYear>2100)){
      setError(t('Enter a valid model year (1900–2100).','أدخل سنة موديل صحيحة بين 1900 و2100.'));return;
    }
    if(readingChanged&&(!Number.isFinite(Number(odometer))||Number(odometer)<0||correctionReason.trim().length<5)){
      setError(t('Enter a non-negative odometer and a correction reason (at least 5 characters).','أدخل قراءة عداد صحيحة وسبب التصحيح بخمسة أحرف على الأقل.'));return;
    }
    const changes:VehicleUpdate={};
    if(updatedPlate!==vehicle.plate_number)changes.plate_number=updatedPlate;
    if(updatedModel!==vehicle.make_model)changes.make_model=updatedModel;
    if(updatedYear!==vehicle.year)changes.year=updatedYear;
    if(updatedDoor!==(vehicle.door_number||null))changes.door_number=updatedDoor;
    if(updatedDriver!==(vehicle.assigned_driver_id??null))changes.assigned_driver_id=updatedDriver;
    if(readingChanged){changes.odometer_correction_km=Number(odometer);changes.odometer_correction_reason=correctionReason.trim();}
    setBusy(true);
    try{await onSave(changes);}catch(err){setError(err instanceof Error?err.message:String(err));}
    finally{setBusy(false);}
  }

  return <section className="nq-vehicle-editor" dir={ar?'rtl':'ltr'} aria-label={t('Edit vehicle','تعديل المركبة')}>
    <div className="nq-ve-breadcrumb"><button type="button" onClick={close} className="nq-ve-back">{ar?<ArrowRight size={16}/>:<ArrowLeft size={16}/>} {t('All vehicles','كل المركبات')}</button><span>/</span><strong>{vehicle.plate_number}</strong></div>
    <form onSubmit={save}>
      <header className="nq-ve-header">
        <div className="nq-ve-header-title"><div className="nq-ve-title-icon"><CarFront size={25}/></div><div><span className="nq-ve-kicker">{t('FLEET ASSET · VEHICLE DETAILS','أصول الأسطول · تفاصيل المركبة')}</span><h2>{canEdit?t('Edit vehicle','تعديل المركبة'):t('Vehicle details','تفاصيل المركبة')} <span>{vehicle.plate_number}</span></h2><p>{t('Update all existing vehicle fields in one place.','تعديل جميع حقول المركبة الحالية من صفحة واحدة.')}</p></div></div>
        <div className="nq-ve-header-actions"><span className="nq-ve-availability"><BadgeCheck size={16}/>{t('Registered','مسجلة')}</span><button type="button" className="nq-ve-cancel" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button>{canEdit&&<button className="nq-ve-save" type="submit" disabled={busy||!hasChanges}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button>}</div>
      </header>
      <div className="nq-ve-workspace">
        <aside className="nq-ve-aside" aria-label={t('Vehicle sections','أقسام المركبة')}>
          <div className="nq-ve-preview"><div className="nq-ve-car"><CarFront size={54} strokeWidth={1.45}/></div><strong>{vehicle.plate_number}</strong><small>{vehicle.make_model||'—'}</small><div className="nq-ve-preview-company">{companyName}</div></div>
          <nav className="nq-ve-sections"><a href="#nq-vehicle-details"><ClipboardList size={17}/>{t('Asset details','تفاصيل المركبة')}</a><a href="#nq-vehicle-assignment"><UserRound size={17}/>{t('Driver assignment','تعيين السائق')}</a><a href="#nq-vehicle-odometer"><Gauge size={17}/>{t('Meter readings','قراءة العداد')}</a></nav>
          <div className="nq-ve-aside-tip"><Wrench size={18}/><p>{t('Maintenance, hardware and trip records remain on their existing pages.','تبقى الصيانة وأجهزة التتبع والرحلات في صفحاتها الحالية.')}</p></div>
        </aside>
        <div className="nq-ve-main">
          <section id="nq-vehicle-details" className="nq-ve-section"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><ClipboardList size={19}/></span><div><h3>{t('Asset details','تفاصيل المركبة')}</h3><p>{t('Vehicle identity and registration information','بيانات هوية المركبة والتسجيل')}</p></div></div>
            <div className="nq-ve-fields">
              <label>{t('Plate number','رقم اللوحة')} <span className="nq-ve-required">*</span><input required maxLength={40} value={plate} onChange={e=>setPlate(e.target.value)} disabled={!canEdit}/></label>
              <label>{t('Company / fleet','الشركة / الأسطول')}<input value={companyName} readOnly aria-readonly="true" title={t('Company cannot be changed here','لا يمكن تغيير الشركة هنا')}/></label>
              <label>{t('Make and model','الشركة المصنعة والموديل')} <span className="nq-ve-required">*</span><input required maxLength={120} value={model} onChange={e=>setModel(e.target.value)} disabled={!canEdit} placeholder="Toyota Camry"/></label>
              <label>{t('Model year','سنة الموديل')}<input type="number" min="1900" max="2100" step="1" value={year} onChange={e=>setYear(e.target.value)} disabled={!canEdit} placeholder="2025"/></label>
              <label>{t('Fleet / door number','رقم الأسطول / الباب')}<input maxLength={40} value={door} onChange={e=>setDoor(e.target.value)} disabled={!canEdit} placeholder="014"/></label>
              <label>{t('Vehicle ID','معرّف المركبة')}<input value={String(vehicle.id)} readOnly aria-readonly="true"/></label>
            </div>
          </section>
          <section id="nq-vehicle-assignment" className="nq-ve-section"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><UserRound size={19}/></span><div><h3>{t('Driver assignment','تعيين السائق')}</h3><p>{t('Assign an available driver from this company','تحديد سائق متاح من نفس الشركة')}</p></div></div>
            <div className="nq-ve-fields"><label>{t('Assigned driver','السائق المعيّن')}<select value={driver} onChange={e=>setDriver(e.target.value)} disabled={!canEdit}><option value="">{t('Unassigned — no driver','غير معيّن — بدون سائق')}</option>{eligibleDrivers.map(d=><option key={d.id} value={d.id}>{d.full_name} (#{d.id})</option>)}{driver!==''&&!eligibleDrivers.some(d=>String(d.id)===driver)&&<option value={driver}>{assigned?.full_name||`#${driver}`}</option>}</select></label><div className="nq-ve-info"><BadgeCheck size={17}/>{t('Existing vehicle / driver assignment rules remain enforced by Nuqati.','تبقى قواعد الربط والتسليم بين المركبة والسائق مفعّلة في نقاطي.')}</div></div>
          </section>
          <section id="nq-vehicle-odometer" className="nq-ve-section"><div className="nq-ve-section-heading"><span className="nq-ve-section-icon"><Gauge size={19}/></span><div><h3>{t('Meter readings','قراءة العداد')}</h3><p>{t('Current mileage and audited administrator corrections','المسافة الحالية وتصحيحات المدير الموثقة')}</p></div></div>
            <div className="nq-ve-fields"><label>{t('Current odometer (km)','قراءة العداد الحالية (كم)')}<input type="number" step="0.1" min="0" value={odometer} onChange={e=>setOdometer(e.target.value)} disabled={!canCorrectOdometer||!canEdit} placeholder={t('Not recorded','غير مسجّل')}/></label><div className="nq-ve-info"><Gauge size={17}/>{canCorrectOdometer?t('Changing this value creates a dated correction in odometer history.','تغيير هذا الرقم يسجل تصحيحاً مؤرخاً في سجل العداد.'):t('Only the Super Admin may correct the odometer. Record normal readings on the Odometer page.','تصحيح العداد للمدير العام فقط. يمكن تسجيل القراءات العادية من صفحة العداد.')}</div>
              {readingChanged&&<label className="nq-ve-wide">{t('Reason for odometer correction','سبب تصحيح العداد')} <span className="nq-ve-required">*</span><textarea required minLength={5} maxLength={500} rows={3} value={correctionReason} onChange={e=>setCorrectionReason(e.target.value)} placeholder={t('Explain why the reading is being corrected','اشرح سبب تصحيح قراءة العداد')}/></label>}
            </div>
          </section>
          {error&&<div className="nq-ve-error" role="alert">{error}</div>}
          <footer className="nq-ve-footer"><span>{hasChanges?t('Unsaved changes','تغييرات غير محفوظة'):t('All fields are up to date','البيانات محدثة')}</span><div><button type="button" className="nq-ve-cancel" onClick={close} disabled={busy}>{t('Cancel','إلغاء')}</button>{canEdit&&<button type="submit" className="nq-ve-save" disabled={busy||!hasChanges}><Save size={17}/>{busy?t('Saving…','جارٍ الحفظ…'):t('Save all changes','حفظ جميع التغييرات')}</button>}</div></footer>
        </div>
      </div>
    </form>
  </section>;
}
