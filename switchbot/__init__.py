"""Library to handle connection with Switchbot"""
import time

import binascii
import logging

import bluepy

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


class Switchbot:
    """Representation of a Switchbot."""

    def __init__(self, mac, retry_count=DEFAULT_RETRY_COUNT, password=None) -> None:
        self._mac = mac
        self._device = None
        self._retry_count = retry_count
        self._lastBattRefresh = 0
        self._battery_percent = None
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
        send_success = False
        command = self._commandkey(key, action)
        _LOGGER.debug("Sending command to switchbot %s", command)
        try:
            self._connect()
            if (action):
                send_success = self._writekey(command)
            else:
                self._getBatteryPercent_FWVersion(command)
             
        except bluepy.btle.BTLEException:
            _LOGGER.warning("Error talking to Switchbot.", exc_info=True)
        finally:
            self._disconnect()
        if send_success:
            return True
        if retry < 1:
            _LOGGER.error("Switchbot communication failed. Stopping trying.", exc_info=True)
            return False
        _LOGGER.warning("Cannot connect to Switchbot. Retrying (remaining: %d)...", retry)
        time.sleep(DEFAULT_RETRY_TIMEOUT)
        return self._sendcommand(key, retry - 1, action)

    def _getBatteryPercent_FWVersion(self, command):
        now = time.time()
        """if self._lastBattRefresh + BATTERY_CHECK_TIMEOUT_SECONDS >= now:"""
        """return"""
        self._device.setDelegate(SwitchBotSettingsNotificationDelegate(self))
        handler = bluepy.btle.Characteristic(self._device, "0014", 20, None, 20)
        handler.write(binascii.a2b_hex("0100"))
        self._writekey(command)

        if self._device.waitForNotifications(BLE_NOTIFICATION_WAIT_TIME_SECONDS):
            _LOGGER.info("Switchbot got batt notification!")
            self._lastBattRefresh = time.time()
        time.sleep(1)
        _LOGGER.info("DONE Waiting...")

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

class SwitchBotSettingsNotificationDelegate(bluepy.btle.DefaultDelegate):
    def __init__(self, params):
        bluepy.btle.DefaultDelegate.__init__(self)
        _LOGGER.info("Setup switchbot delegate: %s", params)
        self._driver = params

    def handleNotification(self, cHandle, data):
        _LOGGER.info("********* Switchbot notification ************* - [Handle: %s] Data: %s", cHandle, data )
        _LOGGER.info("********* Switchbot notification ************* - [Handle: %s] Data: %s", cHandle, data.hex() )
        batt = data[1] #int.from_bytes(data[1], byteorder='big')
        firmware_version = data[2] / 10.0
        _LOGGER.debug("Got SwitchBot battery: %d FW Version: %f", batt, firmware_version)
        self._driver._battery_percent = batt


