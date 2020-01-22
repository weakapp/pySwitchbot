"""Library to handle connection with Switchbot"""
import time

import binascii
import logging

import bluepy

from enum import Enum

DEFAULT_RETRY_COUNT = 3
DEFAULT_RETRY_TIMEOUT = .2

UUID = "cba20d00-224d-11e6-9fb8-0002a5d5c51b"
HANDLE = "cba20002-224d-11e6-9fb8-0002a5d5c51b"
INFO_HANDLE = "cba20003-224d-11e6-9fb8-0002a5d5c51b"

ACTION_PREFIX = "5701"
INFO_PREFIX = "5702"

ACTION_PWD_PREFIX = "5711"
INFO_PWD_PREFIX = "5712"

ACTION_PRESS = ""
ACTION_ON = "01"
ACTION_OFF = "02"

INFO_GET = ""

BATTERY_CHECK_TIMEOUT_SECONDS = 3600.0  # only get batt at most every 60 mins
BLE_NOTIFICATION_WAIT_TIME_SECONDS = 3.0

_LOGGER = logging.getLogger(__name__)

class ActionStatus(Enum):
    complete = 1
    device_busy = 3
    device_wrong_mode = 5
    device_unreachable = 11
    device_encrypted  = 7
    device_unencrypted = 8
    wrong_password = 9

    unable_resp = 254
    unable_connect = 255

    def msg(self): 
        if self == ActionStatus.complete:
            msg = "action complete"
        elif self == ActionStatus.device_busy:
            msg = "switchbot is busy"
        elif self == ActionStatus.device_wrong_mode:
            msg = "switchbot is unable to do this request"
        elif self == ActionStatus.device_unreachable:
            msg = "switchbot is unreachable"
        elif self == ActionStatus.device_encrypted:
            msg = "switchbot is encrypted"
        elif self == ActionStatus.device_unencrypted:
            msg = "switchbot is unencrypted"
        elif self == ActionStatus.wrong_password:
            msg = "switchbot password is wrong"
        elif self == ActionStatus.unable_resp:
            msg = "switchbot does not respond"
        elif self == ActionStatus.unable_connect:
            msg = "switchbot unable to connect"
        else:
            raise ValueError("unknown action status: " + str(self))
        return msg

class Switchbot:
    """Representation of a Switchbot."""

    def __init__(self, mac, retry_count=DEFAULT_RETRY_COUNT, password=None) -> None:
        self._mac = mac
        self._device = None
        self._retry_count = retry_count
        self._last_batt_refresh = 0
        self._battery_percent = None
        self._cmd_response = False
        self._cmd_complete = False
        self._cmd_status = None
        if password is None or password == "":
            self._password_encoded = None
        else:
            self._password_encoded = '%x' % (binascii.crc32(password.encode('ascii')) & 0xffffffff)

    def _connect(self) -> None:
        if self._device is not None:
            return
        try:
            _LOGGER.debug("Connecting to Switchbot...")
            self._device = bluepy.btle.Peripheral(self._mac,
                                                  bluepy.btle.ADDR_TYPE_RANDOM)
            _LOGGER.debug("Connected to Switchbot.")
        except bluepy.btle.BTLEException:
            _LOGGER.debug("Failed connecting to Switchbot.", exc_info=True)
            self._device = None
            raise

    def _disconnect(self) -> None:
        if self._device is None:
            return
        _LOGGER.debug("Disconnecting")
        try:
            self._device.disconnect()
        except bluepy.btle.BTLEException:
            _LOGGER.warning("Error disconnecting from Switchbot.", exc_info=True)
        finally:
            self._device = None

    def _commandkey(self, key, action=True) -> str:
        if self._password_encoded is None:
            if (action):
                return ACTION_PREFIX + key
            else:
                return INFO_PREFIX + key

        if (action):
            return ACTION_PWD_PREFIX + self._password_encoded + key
        else:
            return INFO_PWD_PREFIX + self._password_encoded + key
        
    def _writekey(self, key) -> bool:
        _LOGGER.debug("Prepare to send")
        hand_service = self._device.getServiceByUUID(UUID)
        hand = hand_service.getCharacteristics(HANDLE)[0]
        _LOGGER.debug("Sending command, %s", key)
        write_result = hand.write(binascii.a2b_hex(key), withResponse=True)
        if not write_result:
            _LOGGER.error("Sent command but didn't get a response from Switchbot confirming command was sent. "
                          "Please check the Switchbot.")
        else:
            _LOGGER.info("Successfully sent command to Switchbot (MAC: %s).", self._mac)
        return write_result

    def _sendcommand(self, key, retry, action=True) -> bool:
        retry = retry - 1
        exception = False
        command = self._commandkey(key, action)
        _LOGGER.debug("Sending command to switchbot %s", command)
        try:
            self._connect()

            self._cmd_response = False
            self._cmd_complete = False
            self._cmd_status = None
            if (action):
                self._doAction(command)
            else:
                self._getInfo(command)
             
        except bluepy.btle.BTLEException:
            exception = True
            if retry < 0: 
                _LOGGER.warning("Error talking to Switchbot.", exc_info=True)
        finally:
            self._disconnect()
        if self._cmd_complete:
            return True
        if retry >= 0:
            time.sleep(DEFAULT_RETRY_TIMEOUT)
            return self._sendcommand(key, retry, action)
        else:
            if exception == False:
                _LOGGER.error("Switchbot communication failed. status: %s", self._cmd_status)
                if self._cmd_response:
                    _LOGGER.error("Switchbot communication failed. status: %s", self._cmd_status)
                else:
                    _LOGGER.error("Switchbot communication failed. no response")
        return self._cmd_complete

    def _doAction(self, command) -> None:
        self._device.setDelegate(ActionNotificationDelegate(self))
        handler = bluepy.btle.Characteristic(self._device, "0014", 20, None, 20)
        handler.write(binascii.a2b_hex("0100"))
        self._writekey(command)
        self._device.waitForNotifications(BLE_NOTIFICATION_WAIT_TIME_SECONDS)
        time.sleep(1)

    def _getInfo(self, command) -> None:
        now = time.time()
        #if self._lastBattRefresh + BATTERY_CHECK_TIMEOUT_SECONDS >= now:
        #    return
        self._device.setDelegate(InfoNotificationDelegate(self))
        handler = bluepy.btle.Characteristic(self._device, "0014", 20, None, 20)
        handler.write(binascii.a2b_hex("0100"))
        self._writekey(command)

        if self._device.waitForNotifications(BLE_NOTIFICATION_WAIT_TIME_SECONDS):
            self._last_batt_refresh = time.time()
        time.sleep(1)

    def turn_on(self) -> bool:
        """Turn device on."""
        return self._sendcommand(ACTION_ON, self._retry_count)

    def turn_off(self) -> bool:
        """Turn device off."""
        return self._sendcommand(ACTION_OFF, self._retry_count)

    def press(self) -> bool:
        """Press command to device."""
        return self._sendcommand(ACTION_PRESS, self._retry_count)
    
    def getSettings(self) -> None:
        """Get Switchbot settings."""
        self._sendcommand(INFO_GET, self._retry_count, False)

class ActionNotificationDelegate(bluepy.btle.DefaultDelegate):
    def __init__(self, params):
        bluepy.btle.DefaultDelegate.__init__(self)
        _LOGGER.info("Setup switchbot delegate: %s", params)
        self._driver = params

    def handleNotification(self, cHandle, data):
        self._driver._cmd_response = True
        _LOGGER.debug("********* Switchbot notification ************* - [Handle: %s] Data: %s", cHandle, data.hex() )
        action_status = ActionStatus(data[0])

        if action_status is not ActionStatus.complete:
            self._driver._cmd_complete = False
            self._driver._cmd_status = action_status.msg()
        else:
            self._driver._cmd_complete = True

class InfoNotificationDelegate(bluepy.btle.DefaultDelegate):
    def __init__(self, params):
        bluepy.btle.DefaultDelegate.__init__(self)
        _LOGGER.info("Setup switchbot delegate: %s", params)
        self._driver = params

    def handleNotification(self, cHandle, data):
        self._driver._cmd_response = True
        _LOGGER.info("********* Switchbot notification ************* - [Handle: %s] Data: %s", cHandle, data.hex() )
        action_status = ActionStatus(data[0])

        if action_status is not ActionStatus.complete:
            self._driver._cmd_complete = False
            self._driver._cmd_status = action_status.msg()
        else:
            self._driver._cmd_complete = True
            batt = data[1]
            firmware_version = data[2] / 10.0
            self._driver._battery_percent = batt
            _LOGGER.debug("Got SwitchBot battery: %d FW Version: %f", batt, firmware_version)


