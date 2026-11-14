"""Nuqati Teltonika TCP receiver, Codec 8 and 8E (FMC920 pilot).
Run separately: python -m app.teltonika_receiver. No HTTP/FASTAPI exposed.
"""
import asyncio, ipaddress, json, logging, os, struct
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from .db import SessionLocal
from .hardware import ensure_tables

log=logging.getLogger('nuqati.teltonika')
MAX_FRAME=128*1024
# DB calls always run outside the asyncio networking loop.
_DB_CONCURRENCY=asyncio.Semaphore(max(1,int(os.getenv('TELTONIKA_MAX_DB_CONCURRENCY','16'))))


def remote_is_allowed(peer) -> bool:
    """Optional secondary CIDR allowlist; primary protection is host bind/VPN/firewall.

    Teltonika Codec 8/8E IMEI handshake has no cryptographic device secret.
    """
    ranges=os.environ.get('TELTONIKA_ALLOWED_CIDRS','').strip()
    if not ranges:
        return True  # Compose binds to localhost unless explicitly configured.
    try:
        remote=ipaddress.ip_address(peer[0])
        return any(remote in ipaddress.ip_network(cidr.strip(),strict=False)
                   for cidr in ranges.split(',') if cidr.strip())
    except (ValueError, TypeError, IndexError):
        return False


def known_device(imei:str) -> bool:
    with SessionLocal() as db:
        return bool(db.execute(text("SELECT 1 FROM telematics_devices WHERE imei=:i AND vendor='teltonika' AND enabled=TRUE"),{'i':imei}).first())


async def db_work(func,*args):
    async with _DB_CONCURRENCY:
        return await asyncio.to_thread(func,*args)


def crc16_ibm(data:bytes)->int:
    crc=0
    for b in data:
        crc^=b
        for _ in range(8):
            crc=(crc>>1)^0xA001 if crc&1 else crc>>1
    return crc&0xffff

class Reader:
    def __init__(self,b:bytes):self.b=b;self.p=0
    def read(self,n):
        if n<0 or self.p+n>len(self.b):raise ValueError('Truncated AVL packet')
        x=self.b[self.p:self.p+n];self.p+=n;return x
    def num(self,n,signed=False):return int.from_bytes(self.read(n),'big',signed=signed)

def parse_avl(payload:bytes):
    r=Reader(payload);codec=r.num(1)
    if codec not in (0x08,0x8e):raise ValueError('Unsupported codec')
    count=r.num(1)
    if count>100:raise ValueError('Too many AVL records')
    out=[];wide=codec==0x8e;id_len=2 if wide else 1
    for _ in range(count):
        timestamp_ms=r.num(8);priority=r.num(1)
        longitude=r.num(4,True)/1e7;latitude=r.num(4,True)/1e7
        altitude=r.num(2,True);angle=r.num(2);satellites=r.num(1);speed=r.num(2)
        event_id=r.num(id_len);total=r.num(id_len)
        io={};io_count=0
        for size in (1,2,4,8):
            n=r.num(id_len);io_count+=n
            if n>200:raise ValueError('Excessive IO elements')
            for __ in range(n):io[r.num(id_len)]=r.num(size)
        if wide:
            nx=r.num(2);io_count+=nx
            if nx>200:raise ValueError('Excessive variable IO elements')
            for __ in range(nx):
                key=r.num(2);length=r.num(2)
                if length>4096:raise ValueError('Oversized IO value')
                io[key]=r.read(length).hex()
        if io_count!=total:raise ValueError('IO count mismatch')
        if not (-90<=latitude<=90 and -180<=longitude<=180):raise ValueError('Invalid GPS coordinates')
        when=datetime.fromtimestamp(timestamp_ms/1000,timezone.utc)
        if when>datetime.now(timezone.utc)+timedelta(days=1):raise ValueError('Future timestamp')
        out.append(dict(recorded_at=when,latitude=latitude,longitude=longitude,speed_kmh=speed,
                 heading=angle,satellites=satellites,altitude_m=altitude,
                 ignition=bool(io[239]) if 239 in io and isinstance(io[239],int) else None,
                 raw_io=json.dumps({'event_id':event_id,'priority':priority,'io':io},separators=(',',':'))))
    if r.num(1)!=count or r.p!=len(payload):raise ValueError('AVL record count/length mismatch')
    return out

def persist(imei,points):
    with SessionLocal() as db:
        device=db.execute(text('SELECT id,company_id,vehicle_id FROM telematics_devices WHERE imei=:imei AND vendor=\'teltonika\' AND enabled=TRUE'),{'imei':imei}).mappings().first()
        if not device:return False
        for point in points:
            # PostgreSQL idempotency: tracker retry must not duplicate data.
            db.execute(text('''INSERT INTO telematics_points(device_id,company_id,vehicle_id,recorded_at,latitude,longitude,
              speed_kmh,heading,satellites,altitude_m,ignition,accuracy_source,raw_io)
              VALUES (:device_id,:company_id,:vehicle_id,:recorded_at,:latitude,:longitude,
              :speed_kmh,:heading,:satellites,:altitude_m,:ignition,'teltonika_avl',:raw_io)
              ON CONFLICT (device_id,recorded_at,latitude,longitude) DO NOTHING'''),
              {**point,'device_id':device['id'],'company_id':device['company_id'],'vehicle_id':device['vehicle_id']})
        db.execute(text('UPDATE telematics_devices SET last_seen_at=CURRENT_TIMESTAMP WHERE id=:id'),{'id':device['id']})
        db.commit()
    return True

async def receive(reader,writer):
    imei='unknown'
    try:
        if not remote_is_allowed(writer.get_extra_info('peername')):
            log.warning('Rejected tracker connection from non-allowlisted network')
            return
        length=struct.unpack('>H',await asyncio.wait_for(reader.readexactly(2),30))[0]
        if length!=15:writer.write(b'\x00');await writer.drain();return
        imei=(await asyncio.wait_for(reader.readexactly(length),30)).decode('ascii')
        if not imei.isdigit():writer.write(b'\x00');await writer.drain();return
        accepted=await db_work(known_device,imei)
        writer.write(b'\x01' if accepted else b'\x00');await writer.drain()
        if not accepted:return
        while True:
            header=await asyncio.wait_for(reader.readexactly(8),180)
            if header[:4]!=b'\x00'*4:raise ValueError('Invalid preamble')
            size=int.from_bytes(header[4:],'big')
            if size<3 or size>MAX_FRAME:raise ValueError('Invalid packet length')
            payload=await asyncio.wait_for(reader.readexactly(size),60)
            crc_bytes=await asyncio.wait_for(reader.readexactly(4),30)
            if int.from_bytes(crc_bytes,'big')!=crc16_ibm(payload):
                log.warning('CRC failure IMEI suffix=%s',imei[-4:]);break
            points=parse_avl(payload)
            if not await db_work(persist,imei,points):break
            writer.write(struct.pack('>I',len(points)));await writer.drain()
    except (asyncio.IncompleteReadError,asyncio.TimeoutError,ConnectionResetError,BrokenPipeError):pass
    except Exception:
        log.exception('Tracker packet rejected IMEI suffix=%s',imei[-4:])
    finally:
        writer.close()
        try:await writer.wait_closed()
        except Exception:pass

async def main():
    logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))
    bind_host=os.environ.get('TELTONIKA_BIND_HOST','127.0.0.1')
    if bind_host not in ('127.0.0.1','::1','localhost') and not os.environ.get('TELTONIKA_ALLOWED_CIDRS','').strip():
        raise RuntimeError('Public Teltonika TCP receiver requires TELTONIKA_ALLOWED_CIDRS or private VPN/APN')
    ensure_tables()
    port=int(os.getenv('TELTONIKA_PORT','5027'))
    server=await asyncio.start_server(receive,'0.0.0.0',port,limit=MAX_FRAME+1024)
    if not os.environ.get('TELTONIKA_ALLOWED_CIDRS'):
        log.warning('TELTONIKA_ALLOWED_CIDRS is unset: restrict host publishing to loopback/VPN only')
    log.info('Teltonika receiver listening on %s',port)
    async with server:await server.serve_forever()

if __name__=='__main__':asyncio.run(main())
