"""Local calendar export only; does not send invitations."""
import datetime as dt
from .store import digest


def escape(x):
    return x.replace('\\','\\\\').replace('\n','\\n').replace(',','\\,').replace(';','\\;').replace('\r','')


def invitation(title,start,end,description=''):
    a=dt.datetime.fromisoformat(start); b=dt.datetime.fromisoformat(end)
    if a.tzinfo is None or b.tzinfo is None or b<=a: raise ValueError('timezone-aware start/end with end > start required')
    stamp=lambda d:d.astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//JobRequirements//Interview//EN','BEGIN:VEVENT',
           'UID:'+digest(title+start+end)+'@jobrequirements','DTSTAMP:'+stamp(dt.datetime.now(dt.timezone.utc)),
           'DTSTART:'+stamp(a),'DTEND:'+stamp(b),'SUMMARY:'+escape(title),'DESCRIPTION:'+escape(description),'END:VEVENT','END:VCALENDAR']
    # RFC5545 fold at 75 octets without splitting a UTF-8 character.
    out=[]
    for line in lines:
        buf=''
        for char in line:
            if len((buf+char).encode())>75: out.append(buf); buf=' '
            buf+=char
        out.append(buf)
    return '\r\n'.join(out)+'\r\n'
