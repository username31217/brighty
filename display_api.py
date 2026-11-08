"""macOS connection API and session-scoped display positioning."""
import ctypes as C
import ctypes.util


class DisplayAPI:
    def __init__(self):
        self.cg = C.CDLL(ctypes.util.find_library('ApplicationServices'))
        signatures = {
            'CGBeginDisplayConfiguration': ([C.POINTER(C.c_void_p)], C.c_int),
            'CGSConfigureDisplayEnabled': ([C.c_void_p, C.c_uint32, C.c_bool], C.c_int),
            'CGCompleteDisplayConfiguration': ([C.c_void_p, C.c_int], C.c_int),
            'CGCancelDisplayConfiguration': ([C.c_void_p], C.c_int),
            'CGConfigureDisplayOrigin': ([C.c_void_p, C.c_uint32, C.c_int32, C.c_int32], C.c_int),
        }
        for name, (arguments, result) in signatures.items():
            fn = getattr(self.cg, name)
            fn.argtypes, fn.restype = arguments, result

    def set_origins(self, positions):
        """Move already active displays together, without changing power/modes."""
        config = C.c_void_p()
        rc = self.cg.CGBeginDisplayConfiguration(C.byref(config))
        if rc:
            raise RuntimeError(f'Could not begin layout restoration: {rc}.')
        try:
            for number, x, y in positions:
                rc = self.cg.CGConfigureDisplayOrigin(config, number, x, y)
                if rc:
                    raise RuntimeError(f'Could not set coordinates for display {number}: {rc}.')
        except BaseException:
            self.cg.CGCancelDisplayConfiguration(config)
            raise
        # kCGConfigureForSession: positions must survive this CLI process exiting.
        rc = self.cg.CGCompleteDisplayConfiguration(config, 1)
        if rc:
            raise RuntimeError(f'Could not apply the display layout: {rc}.')

    def set_enabled(self, number, enabled):
        if not isinstance(number, int) or not 0 < number <= 0xFFFFFFFF:
            raise RuntimeError('No valid system display ID is available.')
        config = C.c_void_p()
        rc = self.cg.CGBeginDisplayConfiguration(C.byref(config))
        if rc:
            raise RuntimeError(f'macOS: beginning display configuration, code {rc}.')
        try:
            rc = self.cg.CGSConfigureDisplayEnabled(config, number, enabled)
            if rc:
                raise RuntimeError(f'macOS: configuring display {number}, code {rc}.')
        except BaseException:
            self.cg.CGCancelDisplayConfiguration(config)
            raise
        # Keep the tested connection workaround's option (forAppOnly = 0).
        # The private enable API's observed behavior differs from positioning.
        rc = self.cg.CGCompleteDisplayConfiguration(config, 0)
        if rc:
            raise RuntimeError(f'macOS: applying configuration for display {number}, code {rc}.')
