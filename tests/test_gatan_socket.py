"""Pin the GS_* function codes against SEMCCDDefines.h so a transcription
typo (there was already one caught during scaffolding: GET_DM_VERSION_AND_BUILD
was off by one) fails loudly instead of silently talking to the wrong RPC."""

from fastcs_gatan.connection.gatan_socket import FunctionCode


def test_function_codes_match_semccddefines_enum():
    # Order matches the `enum {GS_ExecuteScript = 1, ...}` in
    # /workspaces/SerialEM/Shared/SEMCCDDefines.h (1-indexed).
    assert FunctionCode.SET_CURRENT_CAMERA == 4
    assert FunctionCode.GET_ACQUIRED_IMAGE == 6
    assert FunctionCode.SELECT_CAMERA == 9
    assert FunctionCode.SET_READ_MODE == 10
    assert FunctionCode.GET_NUMBER_OF_CAMERAS == 11
    assert FunctionCode.IS_CAMERA_INSERTED == 12
    assert FunctionCode.INSERT_CAMERA == 13
    assert FunctionCode.GET_DM_VERSION == 14
    assert FunctionCode.GET_DM_CAPABILITIES == 15
    assert FunctionCode.SET_SHUTTER_NORMALLY_CLOSED == 16
    assert FunctionCode.SET_NO_DM_SETTLING == 17
    assert FunctionCode.SET_K2_PARAMETERS == 23
    assert FunctionCode.CHUNK_HANDSHAKE == 24
    assert FunctionCode.SETUP_FILE_SAVING == 25
    assert FunctionCode.GET_FILE_SAVE_RESULT == 26
    assert FunctionCode.SETUP_FILE_SAVING2 == 27
    assert FunctionCode.SET_K2_PARAMETERS2 == 29
    assert FunctionCode.STOP_CONTINUOUS_CAMERA == 30
    assert FunctionCode.GET_PLUGIN_VERSION == 31
    assert FunctionCode.GET_LAST_ERROR == 32
    assert FunctionCode.GET_LAST_DOSE_RATE == 40
    assert FunctionCode.GET_DM_VERSION_AND_BUILD == 42
