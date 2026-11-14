from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, QTimer, Signal

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
HOTKEY_ID = 0xB001
HOTKEY_PROBE_ID = 0xB002

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C

_VK_BY_NAME = {f"F{index}": 0x6F + index for index in range(1, 13)}
_MOD_BY_NAME = {
    "ALT": MOD_ALT,
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN,
    "META": MOD_WIN,
}


class _KbdLlHookStruct(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


_user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if sys.platform == "win32" else None

if _user32 is not None:
    _user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short

    _HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int,
        _HOOKPROC,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    ]
    _user32.SetWindowsHookExW.restype = wintypes.HHOOK
    _user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK,
        ctypes.c_int,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.CallNextHookEx.restype = ctypes.c_ssize_t
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def parse_hotkey(spec: str) -> tuple[int, int]:
    parts = [part.strip().upper() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ValueError("热键不能为空")
    key = parts[-1]
    if key not in _VK_BY_NAME:
        raise ValueError("原型仅支持 F1–F12 作为主键")
    modifiers = 0
    for part in parts[:-1]:
        if part not in _MOD_BY_NAME:
            raise ValueError(f"不支持的修饰键：{part}")
        modifiers |= _MOD_BY_NAME[part]
    return modifiers | MOD_NOREPEAT, _VK_BY_NAME[key]


class _NativeFilter(QAbstractNativeEventFilter):
    def __init__(self, manager: "HotkeyManager") -> None:
        super().__init__()
        self._manager = manager

    def nativeEventFilter(self, event_type, message):  # type: ignore[override]
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                self._manager._emit_pressed()
                return True, 0
        return False, 0


class HotkeyManager(QObject):
    pressed = Signal()
    released = Signal()

    def __init__(self, spec: str = "F1", parent=None) -> None:
        super().__init__(parent)
        self._spec = spec
        self._filter = _NativeFilter(self)
        self._mode: str | None = None
        self._hook_proc = None
        self._hook = None
        self._pressed_emitted = False
        self._modifiers = 0
        self._virtual_key = 0
        self._active = False
        self._release_timer = QTimer(self)
        self._release_timer.setInterval(25)
        self._release_timer.timeout.connect(self._poll_release)

    def register(self) -> tuple[bool, str]:
        if _user32 is None:
            return False, "全局热键仅支持 Windows。"
        try:
            self._modifiers, self._virtual_key = parse_hotkey(self._spec)
        except ValueError as exc:
            return False, f"热键配置无效：{exc}"

        if _user32.RegisterHotKey(None, HOTKEY_ID, self._modifiers, self._virtual_key):
            self._mode = "message"
            self._active = True
            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._filter)
            return True, ""

        register_error = ctypes.get_last_error()
        hook_ok, hook_error = self._install_hook()
        if hook_ok:
            return True, (
                f"{self._spec} 已被其他程序占用（错误码 {register_error}），"
                f"已启用监听模式，仅识别 {self._spec}，不会记录其他按键。"
            )
        return False, (
            f"{self._spec} 注册失败（错误码 {register_error}），"
            f"监听模式也不可用：{hook_error}"
        )

    def unregister(self) -> None:
        self._active = False
        self._pressed_emitted = False
        self._release_timer.stop()
        if self._mode == "message":
            app = QCoreApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._filter)
            if _user32 is not None:
                _user32.UnregisterHotKey(None, HOTKEY_ID)
        elif self._mode == "hook":
            if _user32 is not None and self._hook:
                _user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
        self._mode = None

    def probe(self, spec: str) -> tuple[bool, str]:
        """Check whether a hotkey can be registered without changing the active one."""
        if _user32 is None:
            return False, "全局热键仅支持 Windows。"
        try:
            modifiers, virtual_key = parse_hotkey(spec)
        except ValueError as exc:
            return False, f"热键配置无效：{exc}"

        if (modifiers, virtual_key) == (self._modifiers, self._virtual_key) and self._mode:
            if self._mode == "message":
                return True, ""
            return False, f"{spec} 仍被其他程序占用，无法选择。请换一个组合键。"

        if not _user32.RegisterHotKey(None, HOTKEY_PROBE_ID, modifiers, virtual_key):
            error = ctypes.get_last_error()
            return False, (
                f"{spec} 已被其他程序占用（错误码 {error}），无法选择。请换一个组合键。"
            )
        _user32.UnregisterHotKey(None, HOTKEY_PROBE_ID)
        return True, ""

    def set_spec(self, spec: str, allow_fallback: bool = False) -> tuple[bool, str]:
        try:
            modifiers, virtual_key = parse_hotkey(spec)
        except ValueError as exc:
            return False, f"热键配置无效：{exc}"

        if (
            self._mode == "message"
            and (modifiers, virtual_key) == (self._modifiers, self._virtual_key)
        ):
            self._spec = spec
            return True, ""

        old_spec = self._spec
        old_modifiers = self._modifiers
        old_virtual_key = self._virtual_key

        self.unregister()
        self._spec = spec
        ok, note = self.register()
        if ok and (allow_fallback or not note):
            return True, note

        self.unregister()
        self._spec = old_spec
        self._modifiers = old_modifiers
        self._virtual_key = old_virtual_key
        if old_spec:
            self.register()
        if ok:
            return False, f"{spec} 已被其他程序占用，无法选择。请换一个组合键。"
        return False, note

    def _install_hook(self) -> tuple[bool, str]:
        assert _user32 is not None and _kernel32 is not None
        module = _kernel32.GetModuleHandleW(None)
        self._hook_proc = _HOOKPROC(self._low_level_callback)
        self._hook = _user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._hook_proc,
            module,
            0,
        )
        if not self._hook:
            return False, f"安装键盘监听失败（错误码 {ctypes.get_last_error()}）"
        self._mode = "hook"
        self._active = True
        return True, ""

    def _emit_pressed(self) -> None:
        if not self._active or self._pressed_emitted:
            return
        self._pressed_emitted = True
        if self._mode == "message":
            self._release_timer.start()
        self.pressed.emit()

    def _emit_released(self) -> None:
        if not self._pressed_emitted:
            return
        self._pressed_emitted = False
        self._release_timer.stop()
        if self._active:
            self.released.emit()

    def _poll_release(self) -> None:
        if _user32 is None or not self._active or not self._pressed_emitted:
            self._release_timer.stop()
            return
        if not (_user32.GetAsyncKeyState(self._virtual_key) & 0x8000):
            self._emit_released()

    def _low_level_callback(self, code, w_param, l_param):
        if code == 0 and self._active:
            data = ctypes.cast(l_param, ctypes.POINTER(_KbdLlHookStruct)).contents
            if data.vkCode == self._virtual_key:
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if not self._pressed_emitted and self._modifiers_match():
                        self._pressed_emitted = True
                        self.pressed.emit()
                elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                    self._emit_released()
        return _user32.CallNextHookEx(None, code, w_param, l_param)

    def _modifiers_match(self) -> bool:
        assert _user32 is not None
        ctrl = bool(_user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        shift = bool(_user32.GetAsyncKeyState(VK_SHIFT) & 0x8000)
        alt = bool(_user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        win = bool(
            (_user32.GetAsyncKeyState(VK_LWIN) & 0x8000)
            or (_user32.GetAsyncKeyState(VK_RWIN) & 0x8000)
        )
        wants_ctrl = bool(self._modifiers & MOD_CONTROL)
        wants_shift = bool(self._modifiers & MOD_SHIFT)
        wants_alt = bool(self._modifiers & MOD_ALT)
        wants_win = bool(self._modifiers & MOD_WIN)
        return (ctrl, shift, alt, win) == (wants_ctrl, wants_shift, wants_alt, wants_win)
