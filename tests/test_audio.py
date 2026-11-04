import unittest
from unittest.mock import patch
from handset.audio import AudioManager, choose_device
from handset.audio_bridge import validate

class AudioTests(unittest.TestCase):
    def setUp(self):
        self.devices=[{'id':'a','name':'My iPhone','address':'AA:BB:CC:DD:EE:FF'}, {'id':'b','name':'Other phone','address':None}]
    def test_only_selected_or_uniquely_identified_phone_is_chosen(self):
        self.assertEqual(choose_device(self.devices,preferred='b'),'b')
        self.assertEqual(choose_device(self.devices,address='aa-bb-cc-dd-ee-ff'),'a')
        self.assertEqual(choose_device(self.devices,name='MY IPHONE'),'a')
        self.assertIsNone(choose_device(self.devices,preferred='missing',name='My iPhone'))
        self.assertIsNone(choose_device(self.devices,name='Unknown'))
        self.assertIsNone(choose_device(self.devices,name='My iPhone',address='11:22:33:44:55:66'))
        self.assertIsNone(choose_device(self.devices + [{'id':'c','name':'My iPhone'}],name='My iPhone'))
    def test_connect_reuse_disconnect_and_disabled_preference(self):
        manager=AudioManager();manager._identity['phone']={'DeviceName':'My iPhone'}
        seen=[]
        def command(payload):
            seen.append(payload)
            if payload['action']=='devices': return {'devices':self.devices}
            return {'state':'Opened'}
        with patch('handset.audio.bridge.command',side_effect=command), patch('handset.audio.os.name','nt'):
            manager._tick({'phase':'running','udid':'phone'})
            manager._tick({'phase':'running','udid':'phone'})
            self.assertEqual(manager.status()['phase'],'connected')
            manager._config['enabled']=False
            manager._tick({'phase':'running','udid':'phone'})
            self.assertEqual(manager.status()['phase'],'off')
        self.assertEqual([p['action'] for p in seen],['devices','audio.connect','status','audio.disconnect'])
        self.assertEqual(seen[1]['device'],'a')
    def test_unknown_phone_does_not_connect_an_arbitrary_device(self):
        manager=AudioManager();manager._identity['unknown']={}
        with patch('handset.audio.bridge.command',return_value={'devices':self.devices}) as command,patch('handset.audio.os.name','nt'):
            manager._tick({'phase':'running','udid':'unknown'})
            self.assertEqual(manager.status()['phase'],'setup')
            command.assert_called_once_with({'action':'devices'})
    def test_lost_connection_is_not_reported_as_connected_during_retry_wait(self):
        import time
        manager=AudioManager();manager._active=('phone','a');manager._retry_at=time.monotonic()+30
        manager._state['phase']='connected'
        with patch('handset.audio.bridge.command',return_value={'state':'Closed'}),patch('handset.audio.os.name','nt'):
            manager._tick({'phase':'running','udid':'phone'})
            self.assertEqual(manager.status()['phase'],'connecting')

    def test_no_command_shell_or_other_bluetooth_features(self):
        for payload in ({'action':'cursor.start'},{'action':'notifications.connect'},{'action':'audio.connect','device':''},{'action':'audio.connect','device':'x\0y'}):
            with self.assertRaises(ValueError):validate(payload)
