# Corpus Baseline Report

Files: **260** — aoi: 95, other: 81, udt: 43, controller: 17, routine: 12, rung: 12

## Stage pass rates

| stage | applicable | pass | rate |
|---|---|---|---|
| load | 260 | 260 | 100% |
| parse | 260 | 260 | 100% |
| rungs | 260 | 260 | 100% |
| diagnosis | 17 | 17 | 100% |

**Aggregate rung parse coverage: 2758/2761 (99.89%)**

## Full-project (controller) files

| file | repo | tags | rungs | coverage | diagnosis | time |
|---|---|---|---|---|---|---|
| 3381349dad9dbf7c_MainProgram.L5X | Techno11/KetteringFRCCRobotCode | 37 | 68 | 100.0% | 10/10 | 0.005s |
| 42981e034ed267c2__501CS100_-_Programs_-_ | Biswajit7777/AcesysCodeConversion | 58 | 435 | 100.0% | 10/10 | 0.022s |
| df4368153ca78264_Pumps_Program.L5X | GTMichelli-Dev/northwest-grain-growers | 33 | 63 | 100.0% | 10/10 | 0.055s |
| ecaf1915693debcb_MainProgram_Program.L5X | GTMichelli-Dev/northwest-grain-growers | 61 | 106 | 100.0% | 10/10 | 0.054s |
| 692d23bce203533b_ColorBlending_Program.L | GTMichelli-Dev/northwest-grain-growers | 40 | 25 | 100.0% | 10/10 | 0.044s |
| ce474b4fb75f1870_Scale_Values_Program.L5 | GTMichelli-Dev/northwest-grain-growers | 45 | 80 | 100.0% | 10/10 | 0.007s |
| da979f48f4aa4de2_Dev_PF525_Program.L5X | JeremyMedders/LogixLibraries | 16 | 85 | 100.0% | 8/8 | 0.145s |
| 2cc35b111ff7d571_Dev_PackML_State_Progra | JeremyMedders/LogixLibraries | 4 | 614 | 100.0% | 2/2 | 0.02s |
| 9ba519f6ed816dc5_ModbusSlaveTCP.L5X | Techno11/KetteringFRCCRobotCode | 117 | 171 | 100.0% | 10/10 | 0.032s |
| 20767fb0ba666e16_Unit4_EM01_XYZ_Program. | W-P-I/_WPI-FunctionBlocks | 78 | 264 | 100.0% | 10/10 | 0.063s |
| c722c268fb37e136_complete_with_modules.l | reh3376/acd-l5x-tool-lib | 0 | 100 | 100.0% | 10/10 | 0.012s |
| 5eadab0bca680254_ALD_miami.L5X | ghanemja/senior-design | 48 | 38 | 100.0% | 10/10 | 0.005s |
| cd9c3ef83782774f_Assembly_Controls_Robot | JoaoPJPrioli/PLC_logic_decompiler | 46 | 87 | 100.0% | 10/10 | 0.011s |
| 10018939b99abe4e_WaterTreatment_Main.L5X | jbcre8iv/LogixWeave | 37 | 36 | 100.0% | 10/10 | 0.004s |
| 32bfd0147b12e188_Beginner_Guide.L5X | petem903/studio5000-learning | 53 | 65 | 100.0% | 10/10 | 0.005s |
| 65127bce1c767478_Beginner_Guide_Annotate | petem903/studio5000-learning | 65 | 67 | 100.0% | 10/10 | 0.007s |
| 134cd4670ad63baa_Random_AOI_Test_0104202 | drbitboy/plc_rng | 46 | 24 | 100.0% | 10/10 | 0.009s |

## Hardening worklist (ranked distinct failure signatures)

### 1. [rungs] `RungParseError(recorded): Unexpected end of text inside branch`
- occurrences: 2 across 1 file(s)
- files: 19f6a7910f8cd02a_test.L5X
- example: `dancer/INITIATE_DANCE_SEQUENCE#2`

### 2. [rungs] `RungParseError(recorded): Unexpected character <id> at position <n> in rung: …ONE[]]…`
- occurrences: 1 across 1 file(s)
- files: 19f6a7910f8cd02a_test.L5X
- example: `dancer/INITIATE_DANCE_SEQUENCE#4`
