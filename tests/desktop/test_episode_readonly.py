"""Regression checks for UIA identity and the no-input selected-source boundary."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kolos_states.episode_desktop import UIAObserver, control_runtime_id
from kolos_states.episode_readonly import ReadOnlySelectionObserver, SourceReportObserver
from kolos_states.protocol import clone


class Control:
    """Small UIA provider fixture; duplicate HWNDs model browser fragments."""

    def __init__(self, serial: int, name: str, kind: str = 'ButtonControl') -> None:
        self.serial, self.Name, self.ControlTypeName = serial, name, kind
        self.NativeWindowHandle = 77
        self.ClassName, self.AutomationId = 'Fixture', ''
        self.ProcessId = 1234567
        self.IsOffscreen = self.IsPassword = False
        self.IsEnabled = True
        self.BoundingRectangle = SimpleNamespace(left=0, top=0, right=20, bottom=20)
        self.children: list[Control] = []

    def GetRuntimeId(self) -> list[int]:
        """Return distinct provider IDs even with a shared native window."""
        return [42, 77, self.serial]

    def GetChildren(self) -> list[Control]:
        """Return children without exposing input operations."""
        return self.children

    def Exists(self, *_: object) -> bool:
        """The fixture remains present until the test changes its path."""
        return True


def fixture() -> tuple[ReadOnlySelectionObserver, Control, Control]:
    """Place one source below depth six and bind three explicit context anchors."""
    root = Control(1, 'Selected product', 'WindowControl')
    path, parent = [control_runtime_id(root)], root
    for serial in range(2, 19):
        child = Control(serial, '', 'GroupControl')
        parent.children = [child]
        parent = child
        path.append(control_runtime_id(child))
    sku, identity = Control(20, 'SKU-A'), Control(21, '123456')
    column, budget = Control(22, 'AI budget'), Control(23, '100 ₽')
    parent.children = [sku, identity, column, budget]
    selection = dict(hwnd=77, title=root.Name, scope='Selected product source',
                     anchors=[dict(path=path + [control_runtime_id(c)], text=c.Name)
                              for c in (sku, identity, column)],
                     fields=[dict(name='Daily budget', path=path + [control_runtime_id(budget)])])
    observer = ReadOnlySelectionObserver(selection)
    observer.auto = SimpleNamespace(ControlFromHandle=lambda _: root,
                                    UIAutomationInitializerInThread=nullcontext)
    return observer, root, budget


class RuntimeIdentityTests(unittest.TestCase):
    """Shared HWNDs do not alias elements; true duplicate provider IDs still fail."""

    def test_shared_hwnd_does_not_hide_distinct_elements(self) -> None:
        root = Control(1, 'Window', 'WindowControl')
        root.children = [Control(2, 'First'), Control(3, 'Second')]
        observer = UIAObserver(77)
        observer.auto = SimpleNamespace(ControlFromHandle=lambda _: root,
                                        UIAutomationInitializerInThread=nullcontext)
        self.assertEqual(root.children[0].NativeWindowHandle, root.children[1].NativeWindowHandle)
        with patch('kolos_states.episode_desktop.sys.platform', 'win32'):
            result = observer.observe()
        self.assertEqual(len({o['id'] for o in result['objects']}), 2)
        self.assertEqual({o['descriptor']['name'] for o in result['objects']}, {'First', 'Second'})

    def test_actual_runtime_collision_is_rejected(self) -> None:
        root = Control(1, 'Window', 'WindowControl')
        root.children = [Control(2, 'First'), Control(2, 'Second')]
        observer = UIAObserver(77)
        observer.auto = SimpleNamespace(ControlFromHandle=lambda _: root,
                                        UIAutomationInitializerInThread=nullcontext)
        with patch('kolos_states.episode_desktop.sys.platform', 'win32'):
            with self.assertRaisesRegex(ValueError, 'Ambiguous native control ID'):
                observer.observe()

    def test_empty_runtime_id_needs_a_real_hwnd(self) -> None:
        control = SimpleNamespace(GetRuntimeId=lambda: [], NativeWindowHandle=8)
        self.assertEqual(control_runtime_id(control), 'uia:hwnd:8')
        control.NativeWindowHandle = 0
        with self.assertRaisesRegex(ValueError, 'no usable identity'):
            control_runtime_id(control)


class ReadOnlySelectionTests(unittest.TestCase):
    """Read fresh text through an explicit path without permitting source input."""

    def test_deep_button_caption_reads_new_value_under_same_role(self) -> None:
        observer, _, budget = fixture()
        before = observer.observe()
        budget.Name = '175 ₽'
        after = observer.observe()
        self.assertEqual(before['objects'][0]['value'], '100 ₽')
        self.assertEqual(after['objects'][0]['value'], '175 ₽')
        self.assertEqual(before['objects'][0]['descriptor'], after['objects'][0]['descriptor'])
        self.assertFalse(after['objects'][0]['writable'])
        self.assertGreater(after['version'], before['version'])

    def test_read_is_allowed_but_write_and_activation_are_rejected(self) -> None:
        observer, _, _ = fixture()
        oid = observer.observe()['objects'][0]['id']
        observer.send(dict(kind='read', object=oid))
        for kind in ('write', 'activate'):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'forbids all input'):
                observer.send(dict(kind=kind, object=oid, value='1'))

    def test_context_change_is_rejected(self) -> None:
        for index in range(3):
            observer, _, _ = fixture()
            observer.selection['anchors'][index]['text'] = 'different product or column'
            with self.subTest(anchor=index), self.assertRaisesRegex(ValueError, 'anchor changed'):
                observer.observe()

    def test_changed_path_does_not_fall_back_to_coordinates(self) -> None:
        observer, _, budget = fixture()
        budget.serial = 999
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            observer.observe()

    def test_hidden_or_password_source_is_not_read(self) -> None:
        for flag in ('IsOffscreen', 'IsPassword'):
            observer, _, budget = fixture()
            setattr(budget, flag, True)
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'hidden, protected'):
                observer.observe()

    def test_window_or_process_change_is_rejected(self) -> None:
        for field, value in (('Name', 'Other page'), ('ProcessId', 999)):
            observer, root, _ = fixture()
            observer.observe()
            setattr(root, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                observer.observe()

    def test_combined_observer_does_not_forward_input_to_source(self) -> None:
        source, _, _ = fixture()
        source_obs = source.observe()
        report_obj = clone(source_obs['objects'][0])
        report_obj.update(id='local-report', writable=True)
        report_obj['descriptor'].update(name='Target 1', scope='KolosWorkingEpisodePad||Lab')
        report_obs = dict(source_obs, objects=[report_obj])
        sent: list[dict] = []
        report = SimpleNamespace(hwnd=88, observe=lambda: report_obs, send=sent.append)
        observer = SourceReportObserver(source, report)
        observer.observe()
        for kind in ('write', 'activate'):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                observer.send(dict(kind=kind, object=source_obs['objects'][0]['id'], value='1'))
        self.assertEqual(sent, [])
        observer.send(dict(kind='write', object='local-report', value='175 ₽'))
        self.assertEqual(len(sent), 1)


if __name__ == '__main__':
    unittest.main()
