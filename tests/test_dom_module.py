"""Inventario del transceptor (ENTITY-MIB) y umbrales de voltaje/bias en el DOM."""
import unittest

from sonar.collector import dom
from tests.test_dom import THRESHOLDS, build


class ModuleInfoTests(unittest.TestCase):
    def test_wavelength_from_module_type(self):
        cases = {'GLC-SX-MMD': 850, '1000BaseSX SFP': 850, 'SFP-10G-SR': 850, 'GLC-LH-SMD': 1310,
                 'SFP-10G-LR': 1310, 'GLC-ZX-SMD': 1550, 'GLC-BX-U': 1310, 'SFP-GE-BX10-D': 1490,
                 'CWDM 1550nm SFP': 1550, 'GLC-T': None, '': None}
        for text, nm in cases.items():
            self.assertEqual(dom.wavelength_nm(text), nm, text)

    def test_module_info_skips_empty_fields(self):
        info = dom.module_info(dict(descr='1000BaseSX SFP', model='GLC-SX-MMD', serial='AGM1234', mfg='',
                                    hardware_rev='N/A'))
        self.assertEqual(info, dict(descripcion='1000BaseSX SFP', modelo='GLC-SX-MMD', serie='AGM1234',
                                    longitud_onda_nm=850))
        self.assertIsNone(dom.module_info({}))

    def test_transceiver_carries_module_and_all_thresholds(self):
        thresholds = {**THRESHOLDS, 1041: [(20, 2, 290), (20, 4, 370)], 1042: [(20, 4, 120), (20, 2, 10)]}
        modules = {1039: dict(descr='1000BaseSX SFP', model='GLC-SX-MMD', serial='AGM1234', mfg='CISCO-AGILENT',
                              hardware_rev='V01')}
        optic = build(thresholds=thresholds, modules=modules)[0]
        self.assertEqual(optic['modulo']['serie'], 'AGM1234')
        self.assertEqual(optic['modulo']['longitud_onda_nm'], 850)
        self.assertEqual(optic['umbrales']['voltaje'], dict(baja_alarma=2.9, alta_alarma=3.7))
        self.assertEqual(optic['umbrales']['bias'], dict(alta_alarma=12.0, baja_alarma=1.0))

    def test_without_entity_data_module_is_none(self):
        self.assertIsNone(build()[0]['modulo'])
