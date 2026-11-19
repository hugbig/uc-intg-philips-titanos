"""Session steps, in order (increasing risk)."""

from titan_explore.session import Step
from titan_explore.steps.s01_prep import step_prep
from titan_explore.steps.s02_pairing import step_pairing
from titan_explore.steps.s03_power import step_power
from titan_explore.steps.s04_input import step_active_input
from titan_explore.steps.s05_cec import step_cec
from titan_explore.steps.s06_keys import step_keys
from titan_explore.steps.s07_volume import step_volume
from titan_explore.steps.s08_sources import step_sources
from titan_explore.steps.s09_ambilight import step_ambilight
from titan_explore.steps.s10_picture import step_picture
from titan_explore.steps.s11_notify import step_notify
from titan_explore.steps.s12_philips_app import step_philips_app
from titan_explore.steps.s12_stability import step_stability

STEPS: list[Step] = [
    Step(1, "Preparation", step_prep),
    Step(2, "Pairing (JointSpace, MQTT)", step_pairing),
    Step(3, "Power states and wake-up", step_power),
    Step(4, "Active input", step_active_input),
    Step(5, "HDMI-CEC", step_cec),
    Step(6, "Navigation keys", step_keys),
    Step(7, "Volume with the amplifier", step_volume),
    Step(8, "Sources menu and HDMI calibration", step_sources),
    Step(9, "Ambilight", step_ambilight),
    Step(10, "Picture mode", step_picture),
    Step(11, "Change notifications", step_notify),
    Step(12, "Comparison with the Philips app", step_philips_app),
    Step(13, "Stability under load", step_stability, risky=True),
]
