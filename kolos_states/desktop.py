"""Real I/O boundary: fresh Glaz scan -> guarded input -> result receipt.

Glaz-confirmed clicks in lessons may proceed without a visible selection change.
Keys and Enter still require an observed result. Inputs are never resent.
"""
from __future__ import annotations
import time
import threading
from collections import Counter
from .protocol import action, clone, guard, mark_clicked, observation, observation_key, sensory_features, under, click_continues
from .visual import changed as visual_changed
from .targeting import nearest_icons
from . import object_concepts


class Indeterminate(RuntimeError):
    """An effect may have happened, but no reliable result was observed."""


def observed_change(before: dict, after: dict) -> bool:
    """A missed recognition alone is not positive evidence of a physical effect."""
    added = set(sensory_features(after['features'])) - set(sensory_features(before['features']))
    return bool(added or after['output'] != before['output'] or visual_changed(before, after))


def click_trace(before: dict, after: dict, obj: str, icon: dict) -> dict:
    """Retain a motor trace through highlighting, never through a context change."""
    windows=lambda obs: {f for f in obs['features'] if f.startswith('window:')}
    if (before['focus']!=after['focus'] or before['output']!=after['output']
            or windows(before)!=windows(after) or after.get('own_focus')
            or (after['selected'] and after['selected']!=obj) or visual_changed(before,after)):
        result=clone(after);result.pop('last_clicked',None);result.pop('last_clicked_visual',None);return result
    return mark_clicked(after,obj,icon)


def intersect(a,b):
    return not(a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1])


class DesktopObserver:
    def __init__(self, scan, accessibility):
        self.scan,self.accessibility=scan,accessibility

    def observe(self, *, after=0.0, visual_action=None):
        options = {}
        model = self.model_provider() if getattr(self, 'model_provider', None) else None
        if model:
            from .perception.observer import requests
            planned = requests(model, visual_action)
            if planned: options['visual_requests'] = planned
        raw=self.scan.request(after=after, **options);uia=self.accessibility.read();observed_at=time.time()
        icons,issues,recognized,selected = self._recognized(raw, uia)
        features=sorted(['visible:'+id for id in recognized]+['selected:'+selected,'focus:'+uia['focus']]+([uia['window']] if uia.get('window') else []))
        obs=dict(features=features,icons=icons,selected=selected,focus=uia['focus'],output=uia['output'],cursor=raw['cursor'],version=raw['frame'],
            captured_at=raw['captured_at'],observed_at=observed_at,monitor=raw['monitor'],session=raw['session'],readable=uia['readable'],own_focus=uia['own'],reason=uia['reason'],
            visual_sample=raw.get('visual_sample'),object_issues=issues,foreground=uia.get('foreground'),
            context_valid=uia.get('context_valid',True))
        obs['window_context'] = uia.get('window_context', '')
        obs['object_registry'] = clone(raw.get('object_registry', {}))
        obs['recognition_complete'] = bool(raw.get('complete'))
        excluded = list(raw.get('own_rects', []))
        if raw.get('own_rect'): excluded.append(raw['own_rect'])
        if uia.get('field_bbox'): excluded.append(uia['field_bbox'])
        obs['object_instances'] = [clone(i) for i in raw['icons']
            if not any(intersect(i['bbox'], rect) for rect in excluded)]
        if obs['object_registry']:
            from .window_context import in_foreground
            for instance in obs['object_instances']:
                instance['in_foreground'] = in_foreground(instance, obs.get('foreground'))
        if 'perception_samples' in raw:
            obs['perception_samples'] = raw['perception_samples']
        if model and visual_action:
            from .perception.observer import verify
            obs = verify(model, obs, visual_action)
        return observation(obs)

    def observe_frame(self, *, after: float = 0.0) -> dict:
        """Read current context and pixels without recognizing the selected object."""
        raw = self.scan.request(after=after, mode='frame-only')
        uia = self.accessibility.read()
        features = ['focus:'+uia['focus']]+([uia['window']] if uia.get('window') else [])
        return observation(dict(features=features, icons=[], selected='', focus=uia['focus'],
            output=uia['output'], cursor=raw['cursor'], version=raw['frame'],
            captured_at=raw['captured_at'], observed_at=time.time(), monitor=raw['monitor'],
            session=raw['session'], readable=uia['readable'], own_focus=uia['own'],
            reason=uia['reason'], foreground=uia.get('foreground'), context_valid=uia.get('context_valid',True),
            visual_sample=raw.get('visual_sample'), window_context=uia.get('window_context', '')))

    def _recognized(self, raw: dict, uia: dict) -> tuple[list[dict], dict, set[str], str]:
        """Filter inaccessible regions, retain selection, then resolve nearest copies."""
        icons=[];issues={};recognized=set()
        counts = Counter(icon['id'] for icon in raw['icons'])
        field=uia.get('field_bbox');own=raw.get('own_rect')
        for i in raw['icons']:
            reason = self._icon_issue(i, field, own, duplicates=counts[i['id']] > 1)
            if not ((field and intersect(i['bbox'],field)) or (own and intersect(i['bbox'],own))):
                recognized.add(i['id'])
            if reason:
                issues[i['id']] = reason
                continue
            icons.append(i)
        bounds = uia.get('selected_bbox')
        hits = {i['id'] for i in icons if bounds and intersect(i['bbox'], bounds)}
        selected = next(iter(hits)) if len(hits) == 1 else ''
        icons = nearest_icons(icons, raw['cursor'])
        for i in icons:
            issues.pop(i['id'],None)
            i['ambiguous'] = False
        return icons,issues,recognized,selected

    def observe_for(self, action: dict, *, after: float = 0.0) -> dict:
        """Fresh complete visual verification, independent of the attention cache."""
        return self.observe(after=after, visual_action=action)

    @staticmethod
    def _icon_issue(icon: dict, field, own, *, duplicates: bool = False) -> str:
        """Keep recognition separate from eligibility for desktop actions."""
        obj = icon['id']
        if field and intersect(icon['bbox'],field):
            return 'Объект '+obj+' распознан внутри текстового поля'
        if own and intersect(icon['bbox'],own):
            return 'Объект '+obj+' распознан внутри окна Glaz'
        if icon.get('ambiguous_reason')=='overlap':
            return 'Объект '+obj+' распознан, но под курсором есть неразрешённое пересечение объектов'
        if icon.get('ambiguous') and not duplicates:
            return 'Объект '+obj+' распознан в нескольких местах; нужный экземпляр не подтверждён'
        return ''


class WindowsMotor:
    @staticmethod
    def prepare():
        """Load native input dependencies without creating or sending input."""
        import pyautogui
        from pynput.keyboard import Controller
        return pyautogui,Controller

    def __init__(self):
        self.mouse,Controller=self.prepare()
        self.mouse.FAILSAFE=True;self.keyboard=Controller()

    def send(self, action):
        a=action;kind=a['kind']
        if kind=='move':self.mouse.moveTo(a['x'],a['y'],duration=.12)
        elif kind=='click':self.mouse.click()
        elif kind=='enter':self.mouse.press('enter')
        elif kind=='key':self.keyboard.type(a['value'])
        elif kind!='check':raise ValueError('Неподдерживаемое действие')


class DesktopAdapter:
    def __init__(self, observer, motor, *, stop=None, allow=None, paused=None, timeout=6.0):
        self.observer,self.motor=observer,motor;self.stop=stop or threading.Event()
        self.allow=allow or (lambda:False);self.paused=paused or (lambda:False);self.timeout=timeout;self.sent={};self.receipts={};self._assumed_click=None
        self._continuation=None;self._lost_followup=None

    def clear_click(self, reason: str = '') -> None:
        """A new attempt clears all traces; interruption records a lost continuation."""
        if reason and self._continuation:
            self._lost_followup = dict(action=clone(self._continuation['action']), reason=reason)
        elif not reason:
            self._lost_followup = None
        self._continuation=None;self._assumed_click=None

    def _safe(self):
        if self.stop.is_set():
            self.clear_click('Выбор отменён аварийной остановкой')
            raise InterruptedError('Аварийная остановка')
        if not self.allow():
            self.clear_click('Разрешение на ввод отозвано после клика')
            raise PermissionError('Реальные действия не разрешены')

    def observe(self, *, after: float = 0.0) -> dict:
        """Refresh the screen without losing an already dispatched click receipt."""
        if self._continuation or self._lost_followup:
            self._safe()
            return self._continuation_observation(after=after)
        return self._with_confirmed_click(self.observer.observe(after=after))

    def _continuation_observation(self, a: dict | None = None, *, after: float = 0.0) -> dict:
        # Alternative in-memory observers may implement observe only. The real
        # DesktopObserver always takes the recognition-free frame path.
        observe_frame = getattr(self.observer, 'observe_frame', self.observer.observe)
        trace = self._continuation
        observed = observe_frame(after=max(after, trace['at'] if trace else 0))
        self._safe()
        if trace and trace.get('concept') and not object_concepts.same_context(observed, trace['concept']):
            self.clear_click('Контекст общего объекта изменился после клика')
            trace = None
        if trace:
            if a is not None and a != trace['action']:
                self.clear_click('Enter не соответствует выполненному клику')
            else:
                # The dispatched click already selected an instance. Current
                # focus, window and hover changes do not reconsider that choice.
                observed=mark_clicked(observed, trace['action']['object'], trace['icon'])
                observed['click_followup']=clone(trace['action'])
                if trace.get('concept'): observed['concept_followup']=clone(trace['concept'])
        if self._lost_followup:
            observed=clone(observed)
            for key in ('last_clicked','last_clicked_visual','click_followup'):
                observed.pop(key,None)
            observed['click_followup_invalid']=self._lost_followup['reason']
        return observed

    def _with_confirmed_click(self, observed: dict, obj: str | None = None) -> dict:
        """Carry instance confirmation through recognition changes in the same context."""
        if self._assumed_click:
            target,baseline,icon=self._assumed_click
            if obj is None or obj==target:
                result=click_trace(baseline,observed,target,icon)
                if result.get('last_clicked')==target:return result
            self._assumed_click=None
        return observed

    def execute(self, request, *, expected=None, target_focus=None, allow_unexpected=False, assume_click=False, visual_ack=False, followup=None):
        rid=request['id'];a=request['action']
        if rid in self.receipts:return clone(self.receipts[rid])
        if rid in self.sent:raise Indeterminate('Запрос уже отправлялся; повтор запрещён')
        if followup is not None:
            followup=action(followup)
            if (a['kind']!='click' or followup['kind']!='enter' or followup['object']!=a['object']
                    or followup.get('visual')!=a.get('visual')):
                raise ValueError('Продолжение клика должно быть Enter того же объекта')
        continuation_enter=a['kind']=='enter' and bool(self._continuation or self._lost_followup)
        if a['kind']!='enter':self.clear_click()
        self._safe()
        physical_before=(self._continuation_observation(a) if continuation_enter else self._observe_before(a))
        self._safe()
        before=physical_before
        if a['kind']=='enter' and not continuation_enter:before=self._with_confirmed_click(physical_before,a['object'])
        provider = getattr(self.observer, 'model_provider', None)
        object_concepts.refresh_request(provider() if provider else None, before, request)
        if followup and request.get('object_concept'):
            followup['object'] = a['object']
        reason = (object_concepts.motor_reason(provider() if provider else None, before, request)
                  or self._action_reason(before,a,target_focus))
        if reason:
            r=dict(id=rid,action=clone(a),ok=False,reason=reason,before=before,after=before)
            self.receipts[rid]=r;return clone(r)
        # Do not start a fresh physical effect after a pause received during scanning.
        if self.paused():raise InterruptedError('Пауза до отправки действия; оно не выполнено')
        self._safe()
        stamp=time.time();self.sent[rid]=dict(action=clone(a),at=stamp)
        if a['kind']!='check':self.motor.send(a)
        if followup:
            icon=next(i for i in before['icons'] if i['id']==a['object'])
            self._continuation=dict(action=clone(followup),icon=clone(icon),at=time.time(),
                                    concept=clone(request.get('object_concept')))
            after=mark_clicked(before,a['object'],icon);after['click_followup']=clone(followup)
            if request.get('object_concept'): after['concept_followup']=clone(request['object_concept'])
            r=dict(id=rid,action=clone(a),ok=True,reason='',before=before,after=after,
                   effect_observed=False,verified_by='verified-target-click',prediction_match=False)
            self.receipts[rid]=r;return clone(r)
        if a['kind']=='enter':self.clear_click()
        after,changed=self._await_result(a,physical_before,stamp,expected,allow_unexpected,assume_click,visual_ack)
        if a['kind']=='click':
            icon=next(i for i in before['icons'] if i['id']==a['object'])
            after=click_trace(before,after,a['object'],icon)
            self._assumed_click=((a['object'],clone(after),clone(icon)) if after.get('last_clicked') else None)
        r=dict(id=rid,action=clone(a),ok=True,reason='',before=before,after=after,
               effect_observed=bool(changed and a['kind'] in ('click','enter')),
               verified_by='visual-change' if visual_ack else 'fresh-observation',prediction_match=not expected or observation_key(after)==expected)
        self.receipts[rid]=r;return clone(r)

    @staticmethod
    def _action_reason(before: dict, a: dict, target_focus: str | None) -> str:
        """Device-specific guards supplement, never replace, the graph's guards."""
        reason=guard(before,a)
        if a['kind'] in ('key','enter') and before.get('own_focus') and not click_continues(before,a):
            reason='Фокус находится в Glaz; действие запрещено'
        if a['kind']=='key' and not before.get('readable',False):reason='Нельзя прочитать поле для подтверждения ввода'
        if a['kind']=='key' and target_focus and before['focus']!=target_focus:reason='Фокус сменился после выбора клавиши; ввод запрещён'
        if a['kind']=='move':
            monitor=before.get('monitor')
            if monitor and not(monitor['left']<=a['x']<monitor['left']+monitor['width'] and monitor['top']<=a['y']<monitor['top']+monitor['height']):reason='Координаты вне выбранного монитора'
        return reason

    def _observe_before(self, a: dict) -> dict:
        """A single missed detection permits another fresh scan, never blind input."""
        if a.get('visual'):
            return self.observer.observe_for(a)
        observed=self.observer.observe()
        if a.get('object') and not any(i['id']==a['object'] for i in observed['icons']):
            self._safe()
            observed=self.observer.observe(after=observed.get('captured_at') or 0)
        return observed

    def _await_result(self, a: dict, physical_before: dict, stamp: float, expected: str | None,
                      allow_unexpected: bool, assume_click: bool, visual_ack: bool) -> tuple[dict, bool]:
        """Observe two independent matching frames without resending the input."""
        before=physical_before
        deadline=time.monotonic()+self.timeout;last=None;stable=0;last_capture=None
        while time.monotonic()<deadline:
            self._safe()
            after=(self.observer.observe_for(a, after=stamp) if a.get('visual') and a['kind']!='enter'
                   else self.observer.observe(after=stamp))
            captured=after.get('captured_at')
            if captured is not None and captured==last_capture:continue
            last_capture=captured
            comparison=physical_before
            changed=observed_change(comparison,after)
            if before.get('click_followup') and a['kind']=='enter':
                # New recognition IDs cannot be mistaken for Enter's effect.
                changed=(visual_changed(comparison,after) or after['focus']!=before['focus']
                         or after['output']!=before['output']
                         or {f for f in after['features'] if f.startswith('window:')} !=
                            {f for f in before['features'] if f.startswith('window:')})
            if a['kind']=='move':valid=abs(after['cursor']['x']-a['x'])<=3 and abs(after['cursor']['y']-a['y'])<=3
            elif a['kind']=='check':valid=not guard(after,a)
            elif a['kind']=='key':valid=after['readable'] and after['focus']==before['focus'] and after['output']==before['output']+a['value']
            else:
                valid=(visual_changed(comparison,after) if visual_ack else
                       (changed or (a['kind']=='click' and assume_click)) and (allow_unexpected or not expected or observation_key(after)==expected))
            fingerprint=(observation_key(after),after['output'],after['cursor']['x'] if a['kind']=='move' else 0,after['cursor']['y'] if a['kind']=='move' else 0)
            stable=stable+1 if valid and fingerprint==last else (1 if valid else 0);last=fingerprint
            if valid and stable>=2:return after,changed
        raise Indeterminate('Действие отправлено, но наблюдения не подтвердили результат. Автоматического повтора нет.')
