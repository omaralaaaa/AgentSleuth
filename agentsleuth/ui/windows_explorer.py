"""Select a file by its Windows Shell item ID."""


def reveal_file(path):
    from ctypes import POINTER, WinDLL, byref, c_long, c_uint, c_ulong, c_void_p, c_wchar_p

    ole = WinDLL('ole32')
    shell = WinDLL('shell32')
    initialize = ole.CoInitializeEx
    initialize.argtypes = (c_void_p, c_ulong)
    initialize.restype = c_long
    uninitialize = ole.CoUninitialize
    uninitialize.argtypes = ()
    uninitialize.restype = None
    free = ole.CoTaskMemFree
    free.argtypes = (c_void_p,)
    free.restype = None
    parse = shell.SHParseDisplayName
    parse.argtypes = (c_wchar_p, c_void_p, POINTER(c_void_p), c_ulong, POINTER(c_ulong))
    parse.restype = c_long
    select = shell.SHOpenFolderAndSelectItems
    select.argtypes = (c_void_p, c_uint, POINTER(c_void_p), c_ulong)
    select.restype = c_long

    status = initialize(None, 2)  # COINIT_APARTMENTTHREADED
    if status < 0:
        raise OSError(f'Could not initialize the Windows Shell (0x{status & 0xffffffff:08X}).')
    item = c_void_p()
    try:
        status = parse(str(path.resolve(strict=True)), None, byref(item), 0, None)
        if status < 0 or not item:
            raise OSError(f'File Explorer could not locate {path} (0x{status & 0xffffffff:08X}).')
        # With zero children, Explorer opens the parent and selects this item.
        status = select(item, 0, None, 0)
        if status < 0:
            raise OSError(f'File Explorer could not select {path} (0x{status & 0xffffffff:08X}).')
    finally:
        if item:
            free(item)
        uninitialize()
