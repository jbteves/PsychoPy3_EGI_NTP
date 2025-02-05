#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ECI controls and returns"""

from struct import pack, unpack
from typing import Union
from time import time

from .exceptions import *
from .util import sys_from_bytes, get_ntp_byte, get_ntp_float, sys_to_bytes

blue = '\u001b[34;1m'
reset = '\u001b[0m'

byte_table = {
    "Query": b"Q",
    "NewQuery": b"Y",
    "Exit": b"X",
    "BeginRecording": b"B",
    "EndRecording": b"E",
    "Attention": b"A",
    "ClockSync": b"T",
    "NTPClockSync": b"N",
    "NTPReturnClock": b"S",
    "EventData": b"D",
}

requires_data = ("Query", "ClockSync", "NTPClockSync", "EventData",
                 'NTPReturnClock')
# NOTE: NTPReturnClock does not indicate a need to send an NTPv4 in the
# SDK documentation; however, testing indicates that it is required

allowed_endians = ("NTEL", "MAC-", "UNIX")

# Python converts the bytes to ints when indexing; this is more legible
INT_VAL_I = 73
INT_VAL_S = 83

# compactly named for convenience; milliseconds per second
MPS = 1000

def build_command(cmd: str, data: object = None) -> bytes:
    """
    Builds a byte array for ECI from the provided string and data

    Parameters
    ----------
    cmd: the command to send
    data: the data associated with the command; may be one of several types

    Returns
    -------
    The array of bytes that should be sent over the network

    Raises
    ------
    InvalidECICommand if the command is invalid

    See also
    --------
    InvalidECICommand and subclasses in eci.exceptions.py
    """
    # the byte array to send
    tx = None
    # begin validating
    if cmd not in byte_table:
        raise InvalidECICmd(cmd)
    tx = byte_table[cmd]
    if cmd not in requires_data:
        if data is not None:
            raise ECINoDataAllowed(cmd, data)
        else:
            return tx
    if data is None:
        raise ECIDataRequired(cmd)
    # iterate to validate individual command data requirements:
    if cmd == "Query":
        if data in allowed_endians:
            tx += data.encode("ASCII")
        else:
            raise ECIIllegalEndian(data)
    elif cmd == "ClockSync":
        if not isinstance(data, int):
            raise ECIClockNonInteger(data)
        else:
            tx += sys_to_bytes(data, 4)
    elif cmd == "NTPClockSync" or cmd == 'NTPReturnClock':
        try:
            tx += get_ntp_byte(data)
        except NTPException:
            raise ECINTPInvalid()
    elif cmd == "EventData":
        # TODO: make sure datagram is valid or construct helper
        if isinstance(data, bytes):
            tx += data
        else:
            raise ECIDataNotBytes(data)
    else:
        raise ECIUnknownException()
    return tx


def parse_response(bytearr: bytes) -> Union[bool, float, int]:
    """Parses ECI response

    Parameters
    ----------
    bytearr: the byte array to parse (should be size 1)

    Returns
    -------
    Either True or the value of the ECI Identity

    Raises
    ------
    ECIResponseFailure for all failures
    ECIFailure if the amp responds with failure
    ECINoRecordingDeviceFailure if the failure is a result of no recording
    TypeError if the object passed isn't type bytes
    """
    arrlength = 0
    print(f'{blue}Received amp response: {bytearr}{reset}')
    if isinstance(bytearr, bytes):
        arrlength = len(bytearr)
        if arrlength == 1:
            if bytearr == b'Z' or bytearr == b'I':
                return True
            if bytearr == b'F':
                raise ECIFailure()
            if bytearr == b'R':
                raise ECINoRecordingDeviceFailure()
            if bytearr == b'\x01':
                print('NetStation says 1 for no apparent reason')
                return True
            if bytearr == b'S':
                print('NetStation says S')
                return True
            else:
                raise InvalidECIResponse(bytearr)
        elif arrlength == 2:
            # Identify version number
            # NOTE: this deviates from the SDK documentation, which
            # indicates a 1-byte response
            if bytearr[0] == INT_VAL_I:
                return sys_from_bytes(bytearr[1:])
            else:
                raise InvalidECIResponse(bytearr)
        elif arrlength == 8:
            # We've been given an NTPv4-formatted bytearr
            return get_ntp_float(bytearr)
        elif arrlength == 9:
            # ADMONITION: app and amp behavior diverge incompatibly
            # The APP will put 'S' followed by the NTP bytes
            # The AMP will put NTP bytes followed by 'Z'
            # However, sometimes the amp will ALSO respond with S at the
            # beginning.
            # We've been given an 'S' plus NTPv4-formatted bytearr
            # NOTE: this return of size 9 bytes rather than 8 is not
            # properly documented in the SDK guide
            (seconds, subseconds, char) = unpack('IIc', bytearr)
            if char == b'Z':
                # Amp
                print(
                    f'Above response is: NTP of {seconds} seconds and '
                    f'{subseconds} subseconds'
                )
                return seconds + subseconds * 2**-32
            else:
                # Try S start (amp or app)
                char = bytearr[0]
                # Note: we can't unpack cII because integer alignment
                # forces the char to occupy four bytes, rather than just
                # one. Since unpack is designed to unpack C-structures,
                # this alignment ends up being accounted for.
                (seconds, subseconds) = unpack('II', bytearr[1:])
                if char == INT_VAL_S:
                    return seconds + subseconds * 2**-32
                else:
                    # Just broken
                    raise InvalidECIResponse(bytearr)
        else:
            raise InvalidECIResponse(bytearr)
    else:
        raise InvalidECIResponse(bytearr)


def package_event(
    start: float,
    duration: float,
    event_type: str,
    label: str,
    desc: str,
    data: dict,
):
    """Takes event information and creates appropriate byte string

    Parameters
    ----------
    start: the start time of the event in SECONDS from time of last NTP
    sync
    duration: the duration of the event in SECONDS
    event_type: a four-character string indicating the event type
    label: a <=256-character string for labeling the event
    desc: a <=256-character string for describing the event
    data: a dictionary where each value is a string, number, or boolean,
        and each key is a string. Use this to pass data.
    """
    # Get all data types
    type_start = type(start)
    type_duration = type(duration)
    type_etype = type(event_type)
    type_label = type(label)
    type_desc = type(desc)
    type_data = type(data)

    # Check data types
    if not (isinstance(start, float) or isinstance(start, int)):
        raise TypeError(f'Event start should be number or str, is {type_start}')
    if not (isinstance(duration, float) or isinstance(duration, int)):
        raise TypeError(
            f'Event duration should be number, is {type_duration}'
        )
    if not (duration >= 0.001):
        raise TypeError(
            f'Event duration should be at least 0.001, is {duration}'
        )
    if not isinstance(event_type, str):
        raise TypeError(f'Event type should be str, is {type_etype}')
    len_etype = len(event_type)
    if not len(event_type) == 4:
        raise TypeError(
            f'Event type should have 4 characters, has {len_etype}'
        )
    if not isinstance(label, str):
        raise TypeError(f'Event label should be str, is {type_label}')
    len_label = len(label)
    if not len_label <= 256:
        raise TypeError(
            f'Event label should be <= 256 characters, is {len_label}'
        )
    if not isinstance(desc, str):
        raise TypeError(
            f'Event description should be str, is {type_desc}'
        )
    len_desc = len(desc)
    if not len_desc <= 256:
        raise TypeError(
            'Event description should be <= 256 characters, is' +
            f'{len_desc}'
        )
    if not isinstance(data, dict):
        raise TypeError(f'Event data should be dict, is {type_data}')

    nkeys = len(data.keys())

    # Build block for datagram header
    start_millis = int(start * MPS)
    duration_millis = int(duration * MPS)
    print(
        f'Using start time of {start_millis} milliseconds'
        f' and duration of {duration_millis} milliseconds'
    )
    block = (
        pack('i', start_millis) +
        pack('I', duration_millis) +
        bytes(event_type, 'ascii') +
        pack('B', len_label) + bytes(label, 'ascii') +
        pack('B', len_desc) + bytes(desc, 'ascii') +
        pack('B', nkeys)
    )

    # Build blocks for key-value pairs
    key_block = b''
    for key, value in data.items():
        # Check this key's validity
        if not isinstance(key, str):
            type_key = type(key)
            raise TypeError(
                f'Event data keys should be str, but {key} is {type_key}'
            )
        elif len(key) != 4:
            len_key = len(key)
            raise TypeError(
                'Event data keys should have 4 characters;'
                f' {key} has {len_key}'
            )

        # Check the value's validity
        if isinstance(value, bool):
            ktype = 'bool'
            klen = 1 
            kdata = pack('?', value)
        elif isinstance(value, float):
            ktype = 'doub'
            klen = 8
            kdata = pack('d', value)
        elif isinstance(value, int):
            ktype = 'long'
            klen = 4
            kdata = pack('i', value)
        elif isinstance(value, str):
            ktype = 'TEXT'
            klen = len(value)
            kdata = bytes(value, 'ascii')
        else:
            type_value = type(value)
            raise TypeError(
                'Event data values should be str, bool, or numeric; is' +
                f'{type_value}'
            )

        # Build the key's block
        key_block += (
            bytes(key, 'ascii') +
            bytes(ktype, 'ascii') +
            pack('H', klen) +
            kdata
        )

    # Put all blocks together
    len_all_blocks = len(block) + len(key_block)

    datagram = pack('H', len_all_blocks) + block + key_block
    
    return datagram
