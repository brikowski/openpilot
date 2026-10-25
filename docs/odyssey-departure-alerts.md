# Stopped-traffic notifications

Lead-departure and traffic-ready notifications run whenever the car is onroad, including while
OpenPilot is disengaged. There is no settings toggle. Each notification plays the existing single
prompt chime and displays a small, normal-status popup for three seconds. The normal popup uses
the dark notification style. It wakes a sleeping display; the existing inactivity timer allows
the display to sleep afterward. Safety alerts have higher priority.

The observer requires valid, fresh car, model and radar-state messages, Drive, standstill below
0.1 m/s, a released accelerator and no parking brake. Holding the foot brake is allowed.
It emits at most one notification per vehicle stop. Invalid data clears observation history
without allowing a delivered notification to repeat; vehicle movement allows the next stop to notify.

For lead departure, a lead within 35 m must first remain stationary for two seconds. Its range
must then increase by at least 1.5 m with relative speed above 0.5 m/s for half a second.
Track changes and discontinuous range discard the previous lead observation. Lead loss cannot
trigger a departure or directly switch the same stop into traffic-ready detection.

With no lead seen during the observed stop, a model stop request sustained for two seconds arms
traffic-ready detection. A released model stop request with desired acceleration above 0.2 m/s²
for half a second produces the notification. This is a model stop-to-proceed inference, not a
traffic-light classifier or confirmation of a green light. The popup says "Traffic may be ready".
False positives and missed notifications remain possible; road reliability is unmeasured.

The observer runs beside the planner and publishes one-shot `driverAssistance` flags. `selfdrived`
turns fresh valid flags into permanent-type notification events so they also work while disengaged.
These events have no engagement, disable, override or CAN authority. The planner, `carControl`,
Honda translation, safety limits and CMBS availability are unchanged.

The keep/change/retire decision is **keep as a software-tested notification candidate for supervised
assessment**. Synthetic sequences cover engagement independence, confirmation timing, lead changes,
input faults, rearming, audio, normal popups and safety-alert priority. Mutation checks verify the
principal guards. These tests do not establish real-world detection accuracy.

Sunnypilot was reviewed as a feature reference. Its alert files refer to a
[custom license](https://github.com/sunnypilot/sunnypilot/blob/8e740e0ac680d9a960489c04436a701dd491505c/LICENSE.md)
with additional use and redistribution conditions. This implementation uses this checkout's model
action and lead signals, with original observer code and the existing OpenPilot sound asset;
no Sunnypilot code or assets are incorporated.
