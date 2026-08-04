# Log Validation Ledger

Auto-maintained by `.agents/validate_log.py` (idempotent per route). One row per validated drive. FLAGged watchlist symptoms name the candidate tweak; see `.agents/agents.md` "Cross-Brand Longitudinal Patterns" for status. Authoritative data is the sibling `.jsonl`; this table is the human view. `eng min` / `eng mi` are the coverage behind the row - a clean row off a couple engaged minutes is context, not evidence. `branch` is read from the log's own `initData`, so an A/B stays readable after the fact. **`opendbc` is the submodule commit that `git_commit` pins - THAT is where the tune lives, so group by it, not by branch**, and it is blank when the parent commit is not in the local object store or the tree was dirty. `follow gas`/`follow brk` are RMS(ACCEL_COMMAND - carControl.accel) in each domain. `burst/10s` is the largest number of physical BRAKE_REQUEST edges in any 10-second window; it measures the driver-felt tapping symptom without pretending raw request sign determines the grade-compensated actuator domain.

| date | route | branch | opendbc | eng min | eng mi | crashes | track RMS | passthru RMS | gasf mean | windf mean | follow gas | follow brk | burst/10s | ovr/10m | tko/10m | FLAGS |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-07-25 | 805f87f5e96d128c/0000000e--f97802bf64 | - | - | - | - | 0 | 0.176 | 0.006 | 0.541 | 0.177 | - | - | - | - | - | none |
| 2026-07-25 | 805f87f5e96d128c/00000001--ed594b3fa7 | - | - | - | - | 0 | 0.164 | 0.011 | 0.673 | 0.348 | - | - | - | - | - | brake_pid overshoot, brake-onset jerk bind, stop-approach quality |
| 2026-07-25 | 805f87f5e96d128c/00000004--d1d63a9026 | - | - | - | - | 0 | 0.149 | 0.008 | 0.592 | 0.304 | - | - | - | - | - | none |
| 2026-07-25 | 805f87f5e96d128c/0000000a--3a97dc34b5 | - | - | - | - | 0 | 0.183 | 0.010 | 0.481 | 0.272 | - | - | - | - | - | brake_pid overshoot |
| 2026-07-26 | 805f87f5e96d128c/00000005--8eae3adfa7/a | ody-op-long | 618dc5995f80 | 9.7 | 6.4 | 0 | 0.164 | 0.006 | 0.540 | 0.295 | - | - | - | 0.0 | 3.1 | brake takeovers |
| 2026-07-26 | 805f87f5e96d128c/00000006--70bdd9faae/a | ody-op-long | 7962b8b7cad3 | 14.2 | 11.8 | 0 | 0.125 | 0.027 | 0.548 | 0.168 | - | - | - | 0.0 | 1.4 | none |
| 2026-07-26 | 805f87f5e96d128c/0000000b--4b3a653442/a | ody-op-long | 7962b8b7cad3 | 7.8 | 5.8 | 0 | 0.115 | 0.004 | 0.493 | 0.279 | - | - | - | 0.0 | 1.3 | battery / charging |
| 2026-07-26 | 805f87f5e96d128c/00000015--ab025cd335 | ody-op-long | 7962b8b7cad3 | 47.3 | 54.8 | 0 | 0.094 | 0.005 | 0.554 | 0.133 | - | - | - | 0.0 | 0.2 | none |
| 2026-07-26 | 805f87f5e96d128c/00000016--2ecdd5db52 | ody-op-long | 7962b8b7cad3 | 43.0 | 47.7 | 0 | 0.098 | 0.008 | 0.604 | 0.132 | - | - | - | 0.0 | 0.0 | brake_pid overshoot, brake-onset jerk bind, domain chatter |
| 2026-07-29 | 00000018--ce1aafe0cc | ody-op-long | 7962b8b7cad3 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 00000019--dd9d25cc71 | ody-op-long | 7962b8b7cad3 | 5.6 | 5.1 | 0 | 0.167 | 0.007 | 0.549 | 0.215 | 0.009 | 0.057 | - | 0.0 | 3.6 | brake_pid overshoot, uncommanded brake toggles, device thermal |
| 2026-07-29 | 0000001a--ae75f0959b | ody-op-long | 7962b8b7cad3 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000001b--e87a7334b8 | ody-op-long | 7962b8b7cad3 | 3.7 | 4.2 | 0 | 0.112 | 0.004 | 0.640 | 0.277 | 0.005 | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000001c--20249e5d20 | ody-op-long | 7962b8b7cad3 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000001d--95261b0680 | ody-op-long | 7962b8b7cad3 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000001e--9ca059282b | ody-op-long | 7962b8b7cad3 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000001f--765ef47daf | ody-brake-onset | 1b6048e980f7 | 3.0 | 2.3 | 0 | 0.186 | 0.007 | 0.437 | 0.377 | 0.006 | - | - | 0.0 | 6.6 | ride harshness (felt) |
| 2026-07-29 | 00000020--f4a151246e | ody-brake-onset | 1b6048e980f7 | 4.1 | 3.5 | 0 | 0.176 | 0.012 | 0.533 | 0.259 | 0.010 | 0.053 | - | 0.0 | 2.5 | brake_pid overshoot, low-speed brake/accel conflict, uncommanded brake toggles, stop lurch (felt), sign disagreement |
| 2026-07-29 | 00000024--8899ced3b9 | ody-op-long | 7962b8b7cad3 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 00000025--0d5a75064f | ody-op-long | ec823173de2a | 4.4 | 3.8 | 0 | 0.163 | 0.004 | 0.538 | 0.253 | 0.006 | 0.053 | - | 0.0 | 2.3 | stop lurch (felt) |
| 2026-07-29 | 00000027--c97ff87c6e | ody-op-long | ec823173de2a | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | device thermal |
| 2026-07-29 | 00000028--8dd012049a | ody-op-long | ec823173de2a | 1.3 | 0.7 | 0 | 0.242 | 0.005 | 0.653 | 0.427 | 0.012 | 0.099 | - | 0.0 | 0.0 | brake_pid overshoot, uncommanded brake toggles, stop lurch (felt), device thermal |
| 2026-07-29 | 00000029--c583c86b8f | ody-op-long | ec823173de2a | 3.1 | 1.9 | 0 | 0.192 | 0.004 | 0.570 | 0.348 | 0.004 | 0.107 | - | 0.0 | 3.3 | brake_pid overshoot, uncommanded brake toggles, stop lurch (felt), sign disagreement |
| 2026-07-29 | 0000002a--e9814d0236 | ody-op-long | ec823173de2a | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000002b--668cb1bcab | ody-op-long | ec823173de2a | 1.6 | 1.3 | 0 | 0.194 | 0.003 | 0.600 | 0.427 | 0.009 | - | - | 0.0 | 0.0 | ride harshness (felt) |
| 2026-07-29 | 0000002c--f2abe29ba7 | ody-op-long | ec823173de2a | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000002d--f51b65182a | ody-op-long | ec823173de2a | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 0000002e--9e12aec9ae | ody-op-long | ec823173de2a | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-29 | 00000031--f0620ff07a | ody-op-long | 6d2f79e69d6b | 5.4 | 3.4 | 0 | 0.153 | 0.004 | 0.477 | 0.348 | 0.004 | 0.062 | - | 0.0 | 0.0 | low-speed brake/accel conflict, uncommanded brake toggles, stop lurch (felt), sign disagreement |
| 2026-07-29 | 00000030--384f3f5d1e | ody-op-long | 6d2f79e69d6b | 9.3 | 6.7 | 0 | 0.204 | 0.010 | 0.567 | 0.224 | 0.007 | 0.063 | - | 0.0 | 2.1 | brake_pid overshoot, low-speed brake/accel conflict, uncommanded brake toggles, ride harshness (felt), stop lurch (felt), sign disagreement |
| 2026-07-29 | 0000002f--e897169c3c | ody-op-long | ec823173de2a | 11.0 | 9.0 | 0 | 0.164 | 0.005 | 0.585 | 0.182 | 0.010 | 0.070 | - | 0.9 | 1.8 | uncommanded brake toggles, stop lurch (felt) |
| 2026-07-29 | 00000023--e482ef1653 | ody-brake-onset | 1b6048e980f7 | 24.6 | 15.1 | 0 | 0.176 | 0.007 | 0.544 | 0.146 | 0.009 | 0.040 | - | 0.4 | 2.8 | brake takeovers, low-speed brake/accel conflict, stop lurch (felt), device thermal |
| 2026-07-29 | 00000017--4bde00dfda | ody-op-long | 7962b8b7cad3 | 9.4 | 5.4 | 0 | 0.162 | 0.005 | 0.524 | 0.241 | 0.005 | 0.069 | - | 0.0 | 2.1 | stop lurch (felt) |
| 2026-07-29 | 00000021--1f6710b405 | ody-brake-onset | 1b6048e980f7 | 17.0 | 9.6 | 0 | 0.174 | 0.007 | 0.522 | 0.192 | 0.010 | 0.046 | - | 0.6 | 0.6 | windfactor rail exposure, low-speed brake/accel conflict, stop lurch (felt) |
| 2026-07-29 | 00000032--5cf8edfab7 | ody-op-long | 6d2f79e69d6b | 12.6 | 10.1 | 0 | 0.173 | 0.007 | 0.521 | 0.227 | 0.010 | 0.043 | - | 0.8 | 3.2 | brake takeovers, low-speed brake/accel conflict, uncommanded brake toggles |
| 2026-07-30 | 00000033--2f0ed0c996 | ody-op-long | 12daafe768b6 | 9.5 | 6.7 | 0 | 0.213 | 0.006 | 0.504 | 0.253 | 0.012 | 0.090 | - | 0.0 | 2.1 | brake_pid overshoot, low-speed brake/accel conflict, uncommanded brake toggles, ride harshness (felt), sign disagreement |
| 2026-07-30 | 00000036--4c1998f148 | ody-op-long | b21cb2c323fe | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-30 | 00000034--640ab5c81f | ody-op-long | b21cb2c323fe | 45.8 | 51.7 | 0 | 0.125 | 0.005 | 0.678 | 0.144 | 0.006 | 0.213 | - | 0.0 | 0.7 | brake_pid overshoot, following - brake domain, stop lurch (felt), sign disagreement |
| 2026-07-30 | 00000035--fd634e7aba | ody-op-long | b21cb2c323fe | 48.4 | 51.7 | 0 | 0.123 | 0.007 | 0.472 | 0.122 | 0.006 | 0.046 | - | 0.0 | 0.8 | brake_pid overshoot, sign disagreement |
| 2026-07-30 | 00000037--3c5f8ff19c | ody-op-long | d8f962bf3189 | 3.7 | 2.5 | 0 | 0.179 | 0.004 | 0.442 | 0.459 | 0.007 | 0.033 | 2 | 0.0 | 2.7 | sign disagreement |
| 2026-07-30 | 00000039--82363de3c4 | ody-op-long | d8f962bf3189 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-07-30 | 0000003a--c86961b9f3 | ody-op-long | d8f962bf3189 | 2.0 | 0.6 | 0 | 0.208 | 0.009 | 0.639 | 0.487 | 0.011 | 0.110 | 2 | 0.0 | 0.0 | brake_pid overshoot, stop lurch (felt), sign disagreement |
| 2026-07-30 | 0000003b--aeccafe9e4 | ody-op-long | d8f962bf3189 | 10.5 | 6.1 | 0 | 0.183 | 0.004 | 0.505 | 0.357 | 0.007 | 0.039 | 2 | 1.0 | 1.0 | stop lurch (felt), sign disagreement |
| 2026-08-01 | 00000041--300908db45 | ody-op-long | 82afd9a22743 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-01 | 00000040--ca03731c09 | ody-op-long | 82afd9a22743 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-01 | 0000003f--91b3d5dc5f | ody-op-long | 82afd9a22743 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-01 | 0000003d--b4008dd953 | ody-op-long | 82afd9a22743 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-02 | 00000048--ed0e3ac0b8 | ody-op-long | 01df474580bd | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-02 | 00000047--f71dd29780 | ody-op-long | 01df474580bd | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-02 | 00000046--ff33b83a95 | ody-op-long | 01df474580bd | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-02 | 00000044--02e57d6de9 | ody-op-long | 01df474580bd | 40.8 | 37.4 | 0 | 0.124 | 0.003 | 0.557 | 0.123 | 0.004 | 0.039 | 3 | 0.0 | 0.7 | none |
| 2026-08-02 | 00000049--b95d397532 | ody-op-long | 01df474580bd | 69.2 | 64.2 | 0 | 0.143 | 0.005 | 0.635 | 0.116 | 0.006 | 0.029 | 2 | 0.0 | 1.2 | windfactor rail exposure |
| 2026-08-02 | 0000003c--00ad5f695d | ody-op-long | 82afd9a22743 | 46.2 | 52.1 | 0 | 0.112 | 0.006 | 0.598 | 0.165 | 0.008 | 0.031 | 4 | 0.2 | 0.6 | none |
| 2026-08-02 | 0000003e--aa82d1d1f8 | ody-op-long | 82afd9a22743 | 39.3 | 45.0 | 0 | 0.093 | 0.005 | 0.582 | 0.158 | 0.006 | 0.055 | 2 | 0.0 | 0.0 | brake_pid overshoot |
| 2026-08-02 | 00000042--0802bc4369 | ody-op-long | 82afd9a22743 | 6.5 | 4.1 | 0 | 0.157 | 0.004 | 0.614 | 0.344 | 0.007 | 0.054 | 2 | 0.0 | 1.5 | none |
| 2026-08-02 | 0000004b--938df76703 | ody-op-long | 01df474580bd | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-02 | 0000004a--e95ac7f2e6 | ody-op-long | 01df474580bd | 5.1 | 4.8 | 0 | 0.198 | 0.006 | 0.669 | 0.281 | 0.012 | 0.036 | 2 | 0.0 | 3.9 | brake_pid overshoot, sign disagreement |
| 2026-08-02 | 0000004c--c66974e5d7 | ody-op-long | 01df474580bd | 7.5 | 4.2 | 0 | 0.171 | 0.006 | 0.515 | 0.364 | 0.007 | 0.063 | 3 | 0.0 | 1.3 | none |
| 2026-08-02 | 00000045--4a81f712e4 | ody-op-long | 01df474580bd | 26.4 | 19.1 | 0 | 0.155 | 0.004 | 0.615 | 0.153 | 0.006 | 0.046 | 2 | 0.0 | 0.8 | stop lurch (felt), sign disagreement |
| 2026-08-04 | 00000057--9acd7c11bb | ody-op-long | 01df474580bd | 3.7 | 2.8 | 0 | 0.202 | 0.008 | 0.575 | 0.240 | 0.013 | 0.034 | 2 | 0.0 | 2.7 | sign disagreement |
| 2026-08-04 | 00000054--57a4cbc10f | ody-op-long | 01df474580bd | 1.4 | 0.6 | 0 | 0.247 | 0.008 | 0.710 | 0.508 | 0.012 | 0.065 | 1 | 7.3 | 7.3 | ride harshness (felt), stop lurch (felt), sign disagreement |
| 2026-08-04 | 00000053--bff6460b6d | ody-op-long | 01df474580bd | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-04 | 00000052--f2f76723ca | ody-op-long | 01df474580bd | 1.7 | 1.9 | 0 | 0.167 | 0.003 | 0.709 | 0.283 | 0.012 | - | 0 | 0.0 | 0.0 | none |
| 2026-08-04 | 00000051--1acac44b73 | ody-op-long | 01df474580bd | 3.0 | 1.1 | 0 | 0.280 | 0.009 | 0.781 | 0.450 | 0.016 | 0.038 | 4 | 3.3 | 3.3 | brake_pid overshoot, ride harshness (felt), sign disagreement |
| 2026-08-04 | 00000050--50aff77789 | ody-op-long | 01df474580bd | 8.5 | 5.7 | 0 | 0.183 | 0.006 | 0.583 | 0.350 | 0.006 | 0.050 | 2 | 1.2 | 2.3 | sign disagreement |
| 2026-08-04 | 0000004f--4283a4985a | ody-op-long | 01df474580bd | 5.3 | 6.1 | 0 | 0.104 | 0.005 | 0.621 | 0.305 | 0.010 | - | 0 | 0.0 | 1.9 | none |
| 2026-08-04 | 0000004d--38bae28d12 | ody-op-long | 01df474580bd | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-04 | 00000055--b6c9bb3917 | ody-op-long | 01df474580bd | 4.3 | 1.7 | 0 | 0.376 | 0.012 | 0.631 | 0.420 | 0.031 | 0.038 | 4 | 0.0 | 14.0 | track RMS &#124;aEgo-aTarget&#124;, gasfactor stability, ride harshness (felt), sign disagreement |
| 2026-08-04 | 00000056--9c1708dfa7 | ody-op-long | 01df474580bd | 9.8 | 2.5 | 0 | 0.953 | 0.078 | 0.979 | 0.440 | 0.092 | 0.275 | 11 | 0.0 | 7.1 | track RMS &#124;aEgo-aTarget&#124;, gasfactor stability, accel rail saturation, brake_pid overshoot, following - gas domain, following - brake domain, brake-domain transition bursts, ride harshness (felt), stop lurch (felt) |
| 2026-08-04 | 0000005d--981b3417fe | ody-op-long | 6e6ca0b25458 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-04 | 0000005c--aa1352f7f8 | ody-op-long | 6e6ca0b25458 | 4.1 | 3.1 | 0 | 0.195 | 0.007 | 0.551 | 0.241 | 0.010 | 0.044 | 2 | 0.0 | 2.4 | brake_pid overshoot, sign disagreement |
| 2026-08-04 | 0000005b--1e3c877c2b | ody-op-long | 6e6ca0b25458 | 3.6 | 1.5 | 0 | 0.320 | 0.011 | 0.488 | 0.409 | 0.025 | 0.051 | 2 | 5.6 | 11.2 | ride harshness (felt) |
| 2026-08-04 | 0000005a--3f33268566 | ody-op-long | 6e6ca0b25458 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-04 | 00000059--272f90a4d5 | ody-op-long | 6e6ca0b25458 | 0.0 | 0.0 | 0 | - | - | - | - | - | - | - | 0.0 | 0.0 | none |
| 2026-08-04 | 00000058--f3476dd478 | ody-op-long | 6e6ca0b25458 | 4.6 | 3.6 | 0 | 0.186 | 0.005 | 0.619 | 0.199 | 0.008 | 0.053 | 3 | 0.0 | 2.2 | stop lurch (felt), sign disagreement |
