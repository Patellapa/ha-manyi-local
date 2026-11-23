"""Documented PV/PH1800 configuration registers, exposed read-only.

Do not infer support from a zero/default response: compare with the device menu.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Setting:
    address: int
    name: str
    italian: str
    unit: str | None = None
    scale: float = 1
    labels: tuple[tuple[int, str], ...] = ()
    bit: int | None = None

    @property
    def key(self) -> str:
        suffix = f"_bit{self.bit}" if self.bit is not None else ""
        return f"setting_{self.address}{suffix}"

    def decode(self, raw: int) -> int | float | str:
        if self.bit is not None:
            return "on" if raw & (1 << self.bit) else "off"
        if self.labels:
            return dict(self.labels).get(raw, f"unknown_{raw}")
        return round(raw * self.scale, 2) if self.scale != 1 else raw


ON_OFF = ((0, "off"), (1, "on"))
SETTINGS = (
    Setting(10101, "PV charger enable code", "Codice abilitazione caricatore PV"),
    Setting(10103, "Float voltage", "Tensione mantenimento Float", "V", .1),
    Setting(10104, "Absorption voltage", "Tensione assorbimento", "V", .1),
    Setting(10110, "Battery type", "Tipo batteria", labels=((0, "not_selected"),
        (1, "user_defined"), (2, "lithium"), (3, "sealed_lead"), (4, "AGM"),
        (5, "GEL"), (6, "flooded"))),
    Setting(20101, "Off-grid output enabled", "Uscita off-grid abilitata", labels=ON_OFF),
    Setting(20102, "Output voltage setting", "Tensione uscita impostata", "V", .1),
    Setting(20103, "Output frequency setting", "Frequenza uscita impostata", "Hz", .01),
    Setting(20104, "Power saver enabled", "Risparmio energetico abilitato", labels=ON_OFF),
    Setting(20108, "Battery feed-in enabled", "Immissione batteria in rete abilitata", labels=ON_OFF),
    Setting(20109, "Output source priority", "Priorità sorgente uscita", labels=(
        (1, "SBU"), (2, "SUB"), (3, "UTI"), (4, "SOL"))),
    Setting(20111, "Grid protection standard", "Standard protezione rete", labels=(
        (0, "VDE4105"), (1, "UPS"), (2, "APL"), (3, "GEN"))),
    Setting(20112, "Solar use priority", "Priorità utilizzo solare", labels=((0, "LBU"), (1, "BLU"))),
    Setting(20114, "Max inverter current (AC)", "Corrente massima inverter (AC)", "A", .1),
    Setting(20118, "Stop discharging voltage", "Tensione arresto scarica", "V", .1),
    Setting(20119, "Stop charging voltage", "Tensione arresto carica", "V", .1),
    Setting(20125, "Max grid charging current (DC)", "Corrente massima carica rete (DC)", "A", .1),
    Setting(20127, "Battery low voltage", "Soglia tensione batteria bassa", "V", .1),
    Setting(20128, "Battery high voltage", "Soglia tensione batteria alta", "V", .1),
    Setting(20132, "Max total solar charging current", "Corrente massima carica solare totale", "A", .1),
    Setting(20142, "System settings mask", "Maschera impostazioni sistema"),
    Setting(20143, "Charging source priority", "Priorità sorgente carica", labels=(
        (0, "solar_first"), (2, "solar_and_utility"), (3, "solar_only"))),
    Setting(20145, "BMS control method", "Metodo controllo BMS", labels=((0, "VOL"), (1, "SOC"))),
    Setting(20146, "Low DC cut-off SOC", "SOC spegnimento batteria bassa", "%"),
    Setting(20147, "Stop discharging SOC", "SOC arresto scarica", "%"),
    Setting(20148, "Stop charging SOC", "SOC arresto carica", "%"),
    Setting(20149, "Lithium battery protocol", "Protocollo batteria litio", labels=((0, "MUST"), (8, "8"))),
    Setting(20150, "Second output cut-off voltage", "Tensione distacco seconda uscita", "V", .1),
    Setting(20151, "Second output cut-off SOC", "SOC distacco seconda uscita", "%"),
)

# Preserve the documented bit polarity: "on" means the named flag is set.
SYSTEM_FLAGS = (
    ("Overload restart forbidden", "Riavvio sovraccarico disabilitato"),
    ("Overtemperature restart forbidden", "Riavvio sovratemperatura disabilitato"),
    ("Overload bypass forbidden", "Bypass sovraccarico disabilitato"),
    ("LCD auto paging forbidden", "Scorrimento automatico LCD disabilitato"),
    ("Grid buzzer enabled", "Cicalino rete abilitato"),
    ("Buzzer forbidden", "Cicalino disabilitato"),
    ("LCD backlight always on", "Retroilluminazione LCD sempre accesa"),
    ("Fault recording forbidden", "Registrazione guasti disabilitata"),
    ("Operation on BMS communication fault enabled", "Funzionamento su errore comunicazione BMS abilitato"),
    ("Dual output enabled", "Doppia uscita abilitata"),
)
SETTINGS += tuple(Setting(20142, en, it, bit=bit)
                  for bit, (en, it) in enumerate(SYSTEM_FLAGS))
SETTING_ADDRESSES = tuple(dict.fromkeys(item.address for item in SETTINGS))
