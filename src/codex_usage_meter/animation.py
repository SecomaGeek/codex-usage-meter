"""One monotonic startup timeline, shared by normal and mini views."""
from dataclasses import dataclass
import math

def ease(value):
    value=max(0,min(1,value))
    return (1-math.cos(math.pi*value))/2

@dataclass(frozen=True)
class Frame:
    phase: str
    values: tuple
    outer: tuple
    count: float | None
    active: bool

class BootAnimation:
    UP=1.6
    DOWN=1.15
    CENTER_PEAK=20
    def __init__(self,started,enabled=True):
        self.started=started; self.finished=not enabled; self.landing=None
        self.from_values=(0.,0.); self.from_outer=(100.,100.); self.from_count=0.
        self.target=None; self.last=None; self.duration=.75

    def sample(self,now,values,outer,count):
        target=(tuple(values),tuple(outer),count)
        if self.finished:
            return Frame('live',tuple(values),tuple(outer),count,False)
        elapsed=max(0,now-self.started)
        if elapsed<self.UP:
            p=ease(elapsed/self.UP)*100
            return Frame('up',(p,p),(100-p,100-p),self.CENTER_PEAK*p/100,True)
        if elapsed<self.UP+self.DOWN:
            p=(1-ease((elapsed-self.UP)/self.DOWN))*100
            return Frame('down',(p,p),(100-p,100-p),self.CENTER_PEAK*p/100,True)
        if all(v is None for v in values):
            return Frame('waiting',(None,None),(None,None),None,True)
        if self.landing is None:
            self.landing=now; self.target=target
            self.duration=max(.75,min(count or 0,45)*.055)
        elif target[:1]!=self.target[:1] or count!=self.target[2]:
            current=self._landing_frame(now)
            self.from_values=tuple(v or 0 for v in current.values)
            self.from_outer=tuple(v or 0 for v in current.outer)
            self.from_count=current.count or 0
            self.target=target; self.landing=now
            self.duration=max(.75,abs(min(count or 0,45)-self.from_count)*.055)
        frame=self._landing_frame(now)
        self.last=frame
        if now-self.landing>=self.duration:
            self.finished=True
            return Frame('live',tuple(values),tuple(outer),count,False)
        return frame

    def _landing_frame(self,now):
        progress=ease((now-self.landing)/self.duration)
        values,outer,count=self.target
        interpolate=lambda before,target: None if target is None else before+(target-before)*progress
        return Frame('landing',tuple(interpolate(a,b) for a,b in zip(self.from_values,values)),
                     tuple(interpolate(a,b) for a,b in zip(self.from_outer,outer)),
                     interpolate(self.from_count,min(count,45) if count is not None else None),True)
