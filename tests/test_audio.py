import unittest
from unittest.mock import patch
from handset.audio import AudioManager, choose_device
from handset.audio_bridge import validate

class AudioTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(AudioManager, "_save"))
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

    def test_stale_pairing_cannot_override_current_wifi_identity(self):
        stale = dict(self.devices[0], id='stale', address='00:11:22:33:44:55')
        self.assertEqual(choose_device([stale, *self.devices], 'stale',
                                     'My iPhone', 'AA:BB:CC:DD:EE:FF'), 'a')
        self.assertIsNone(choose_device([stale], 'stale', 'My iPhone', 'AA:BB:CC:DD:EE:FF'))

    def test_failed_open_leaves_receiver_available_until_disconnect(self):
        manager = AudioManager()
        manager.remember_identity('phone', {'BluetoothAddress':self.devices[0]['address']})
        replies = [{'devices': self.devices}, {'state':'Closed', 'listening':True, 'note':'Select this PC'}, {}]
        with patch('handset.audio.bridge.command', side_effect=replies) as command, patch('handset.audio.os.name','nt'):
            manager._tick({'phase':'running', 'udid':'phone'})
            self.assertEqual(manager.status()['phase'], 'listening')
            manager._tick({'phase':'idle'})
            self.assertEqual(command.call_args.args[0], {'action':'audio.disconnect'})

    def test_first_connection_pairs_only_the_mirrored_phone_once(self):
        manager = AudioManager()
        address = self.devices[0]['address']
        manager.remember_identity('phone', {'BluetoothAddress':address})
        replies = [{'devices':[]}, {'paired':True, 'note':'Paired'}, {'devices':self.devices}, {'state':'Opened'}]
        with patch('handset.audio.bridge.command', side_effect=replies) as command, patch('handset.audio.os.name','nt'):
            for _ in range(2):
                manager._tick({'phase':'running', 'udid':'phone'})
            self.assertEqual(command.call_args_list[1].args[0], {'action':'audio.pair','address':address})
            self.assertEqual(manager.status()['phase'], 'connected')
            self.assertEqual(manager._config['phones']['phone'], 'a')

    def test_no_command_shell_or_other_bluetooth_features(self):
        for payload in ({'action':'cursor.start'},{'action':'notifications.connect'},{'action':'audio.connect','device':''},{'action':'audio.connect','device':'x\0y'}):
            with self.assertRaises(ValueError):validate(payload)
