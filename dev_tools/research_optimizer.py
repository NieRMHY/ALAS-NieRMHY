import itertools
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps

import numpy as np
from numba import jit, prange
from tqdm import tqdm
from tqdm.contrib.concurrent import process_map

"""
硬编码的刷新权重和掉落数据
数据来源 https://azur-stats.lyoko.io/, 2022-01-02, 约5w6样本
默认二三期全毕业，二三期定向的权重增加到四期上
假设二三期的项目刷新和四期一样，但没有收益
"""
TARGET_SERIES = int(os.environ.get('RESEARCH_OPTIMIZER_SERIES', '4'))
QUIET = os.environ.get('RESEARCH_OPTIMIZER_QUIET', '') == '1'
BASE_SHIPS = ('Agir', 'Hakuryu', 'Anchorage', 'August', 'Marcopolo')
if TARGET_SERIES == 9:
    TARGET_SHIPS = ('valparaiso', 'maximmelmann', 'duncan', 'takahashi', 'orage')
    TARGET_DR_SHIPS = ('valparaiso', 'maximmelmann')
else:
    TARGET_SHIPS = BASE_SHIPS
    TARGET_DR_SHIPS = ('Agir', 'Hakuryu')
SHIP_NAME_MAP = dict(zip(BASE_SHIPS, TARGET_SHIPS))

# 索引，期数，名称，出现权重，彩图纸掉落，彩图纸掉落，金图纸掉落，金图纸掉落，金图纸掉落，彩装备掉落
PROJECT_TABLE = """
0	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
1	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
2	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
3	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
4	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
5	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
6	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
7	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
8	4	B-4	58.42861987	0	0	0.346666667	0.346666667	0.346666667	0.0588
9	4	B-4	29.21430994	0	0	0.346666667	0.346666667	0.346666667	0.0588
10	4	B-4	29.21430994	0	0	0.346666667	0.346666667	0.346666667	0.0588
11	4	C-6	303.3660224	0	0	0	0	0	0.06
12	4	C-8	205.3100712	0.0645	0.0645	0.151	0.151	0.151	0.08
13	4	C-12	155.8916073	0.079	0.079	0.245333333	0.245333333	0.245333333	0.12
14	4	C-6	303.3660224	0	0	0	0	0	0.06
15	4	C-8	205.3100712	0.0645	0.0645	0.151	0.151	0.151	0.08
16	4	C-12	155.8916073	0.079	0.079	0.245333333	0.245333333	0.245333333	0.12
17	4	Agir-0.5	25.39955239	6	0	0	0	0	0.14
18	4	Agir-2.5	766.6697864	1.2	0	0	0	0	0.04
19	4	Agir-5	485.7871007	2.5	0	0	0	0	0.06
20	4	Agir-8	200.3313937	4	0	0	0	0	0.096
21	4	Hakuryu-0.5	25.39955239	0	6	0	0	0	0.14
22	4	Hakuryu-2.5	766.6697864	0	1.2	0	0	0	0.04
23	4	Hakuryu-5	485.7871007	0	2.5	0	0	0	0.06
24	4	Hakuryu-8	200.3313937	0	4	0	0	0	0.096
25	4	Anchorage-0.5	25.39955239	0	0	9	0	0	0.14
26	4	Anchorage-2.5	766.6697864	0	0	2.25	0	0	0.04
27	4	Anchorage-5	485.7871007	0	0	3.75	0	0	0.06
28	4	Anchorage-8	200.3313937	0	0	6	0	0	0.096
29	4	August-0.5	25.39955239	0	0	0	9	0	0.14
30	4	August-2.5	766.6697864	0	0	0	2.25	0	0.04
31	4	August-5	485.7871007	0	0	0	3.75	0	0.06
32	4	August-8	200.3313937	0	0	0	6	0	0.096
33	4	Marcopolo-0.5	25.39955239	0	0	0	0	9	0.14
34	4	Marcopolo-2.5	766.6697864	0	0	0	0	2.25	0.04
35	4	Marcopolo-5	485.7871007	0	0	0	0	3.75	0.06
36	4	Marcopolo-8	200.3313937	0	0	0	0	6	0.096
37	4	Z-2	203.9216684	0	0	0	0	0	0.024
38	4	A-2	203.9216684	0	0	0	0	0	0.06
39	4	G-1.5	582.001119	0.104	0.104	0.299	0.299	0.299	0.025
40	4	G-2.5	402.5500509	0.135	0.135	0.403333333	0.403333333	0.403333333	0.04
41	4	G-4	305.1449135	0.2585	0.2585	0.723333333	0.723333333	0.723333333	0.12
42	4	G-1.5	582.001119	0.104	0.104	0.299	0.299	0.299	0.025
43	4	G-2.5	402.5500509	0.135	0.135	0.403333333	0.403333333	0.403333333	0.04
44	4	G-4	305.1449135	0.2585	0.2585	0.723333333	0.723333333	0.723333333	0.12
45	4	H-0.5	13.18982706	0.555	0.555	1.616666667	1.616666667	1.616666667	0
46	4	H-1	608.5109359	0.33	0.33	0.97	0.97	0.97	0
47	4	H-2	394.3497965	0.4765	0.4765	1.423333333	1.423333333	1.423333333	0
48	4	H-4	151.9433367	0.665	0.665	1.906666667	1.906666667	1.906666667	0
49	4	H-0.5	13.18982706	0.555	0.555	1.616666667	1.616666667	1.616666667	0
50	4	H-1	608.5109359	0.33	0.33	0.97	0.97	0.97	0
51	4	H-2	394.3497965	0.4765	0.4765	1.423333333	1.423333333	1.423333333	0
52	4	H-4	151.9433367	0.665	0.665	1.906666667	1.906666667	1.906666667	0
53	4	Q-0.5	35.35220753	0	0	0	0	0	0.34
54	4	Q-1	204.8414852	0	0	0	0	0	0.04
55	4	Q-2	104.3558291	0	0	0	0	0	0.08
56	4	Q-4	51.26677518	0	0	0	0	0	0.16
57	4	Q-0.5	35.35220753	0	0	0	0	0	0.34
58	4	Q-1	204.8414852	0	0	0	0	0	0.04
59	4	Q-2	104.3558291	0	0	0	0	0	0.08
60	4	Q-4	51.26677518	0	0	0	0	0	0.16
61	4	Q-0.5	35.35220753	0	0	0	0	0	0.34
62	4	Q-1	204.8414852	0	0	0	0	0	0.04
63	4	Q-2	104.3558291	0	0	0	0	0	0.08
64	4	Q-4	51.26677518	0	0	0	0	0	0.16
65	4	Q-0.5	35.35220753	0	0	0	0	0	0.34
66	4	Q-1	204.8414852	0	0	0	0	0	0.04
67	4	Q-2	104.3558291	0	0	0	0	0	0.08
68	4	Q-4	51.26677518	0	0	0	0	0	0.16
69	4	Q-0.5	35.35220753	0	0	0	0	0	0.34
70	4	Q-1	204.8414852	0	0	0	0	0	0.04
71	4	Q-2	104.3558291	0	0	0	0	0	0.08
72	4	Q-4	51.26677518	0	0	0	0	0	0.16
73	4	T-3	261.8007121	0	0	0	0	0	0.045
74	4	T-4	182.1410987	0	0	0	0	0	0.06
75	4	T-6	107.3408952	0	0	0	0	0	0.09
76	2	B-4	63.85544525	0	0	0	0	0	0
77	2	B-4	63.85544525	0	0	0	0	0	0
78	2	B-4	63.85544525	0	0	0	0	0	0
79	2	B-4	63.85544525	0	0	0	0	0	0
80	2	B-4	63.85544525	0	0	0	0	0	0
81	2	B-4	63.85544525	0	0	0	0	0	0
82	2	B-4	63.85544525	0	0	0	0	0	0
83	2	B-4	63.85544525	0	0	0	0	0	0
84	2	B-4	63.85544525	0	0	0	0	0	0
85	2	B-4	31.92772262	0	0	0	0	0	0
86	2	B-4	31.92772262	0	0	0	0	0	0
87	2	C-6	331.5425296	0	0	0	0	0	0
88	2	C-8	224.3791833	0	0	0	0	0	0
89	2	C-12	170.3707535	0	0	0	0	0	0
90	2	C-6	331.5425296	0	0	0	0	0	0
91	2	C-8	224.3791833	0	0	0	0	0	0
92	2	C-12	170.3707535	0	0	0	0	0	0
93	2	Z-2	222.8618262	0	0	0	0	0	0
94	2	A-2	222.8618262	0	0	0	0	0	0
95	2	G-1.5	636.0571355	0	0	0	0	0	0
96	2	G-2.5	439.9387285	0	0	0	0	0	0
97	2	G-4	333.4866434	0	0	0	0	0	0
98	2	G-1.5	636.0571355	0	0	0	0	0	0
99	2	G-2.5	439.9387285	0	0	0	0	0	0
100	2	G-4	333.4866434	0	0	0	0	0	0
101	2	H-0.5	14.41489259	0	0	0	0	0	0
102	2	H-1	665.0291729	0	0	0	0	0	0
103	2	H-2	430.976838	0	0	0	0	0	0
104	2	H-4	166.0557692	0	0	0	0	0	0
105	2	H-0.5	14.41489259	0	0	0	0	0	0
106	2	H-1	665.0291729	0	0	0	0	0	0
107	2	H-2	430.976838	0	0	0	0	0	0
108	2	H-4	166.0557692	0	0	0	0	0	0
109	2	Q-0.5	38.63570553	0	0	0	0	0	0
110	2	Q-1	223.8670753	0	0	0	0	0	0
111	2	Q-2	114.0483541	0	0	0	0	0	0
112	2	Q-4	56.02841146	0	0	0	0	0	0
113	2	Q-0.5	38.63570553	0	0	0	0	0	0
114	2	Q-1	223.8670753	0	0	0	0	0	0
115	2	Q-2	114.0483541	0	0	0	0	0	0
116	2	Q-4	56.02841146	0	0	0	0	0	0
117	2	Q-0.5	38.63570553	0	0	0	0	0	0
118	2	Q-1	223.8670753	0	0	0	0	0	0
119	2	Q-2	114.0483541	0	0	0	0	0	0
120	2	Q-4	56.02841146	0	0	0	0	0	0
121	2	Q-0.5	38.63570553	0	0	0	0	0	0
122	2	Q-1	223.8670753	0	0	0	0	0	0
123	2	Q-2	114.0483541	0	0	0	0	0	0
124	2	Q-4	56.02841146	0	0	0	0	0	0
125	2	Q-0.5	38.63570553	0	0	0	0	0	0
126	2	Q-1	223.8670753	0	0	0	0	0	0
127	2	Q-2	114.0483541	0	0	0	0	0	0
128	2	Q-4	56.02841146	0	0	0	0	0	0
129	2	T-3	286.1166509	0	0	0	0	0	0
130	2	T-4	199.0582865	0	0	0	0	0	0
131	2	T-6	117.3106719	0	0	0	0	0	0
132	3	B-4	63.20796608	0	0	0	0	0	0
133	3	B-4	63.20796608	0	0	0	0	0	0
134	3	B-4	63.20796608	0	0	0	0	0	0
135	3	B-4	63.20796608	0	0	0	0	0	0
136	3	B-4	63.20796608	0	0	0	0	0	0
137	3	B-4	63.20796608	0	0	0	0	0	0
138	3	B-4	63.20796608	0	0	0	0	0	0
139	3	B-4	63.20796608	0	0	0	0	0	0
140	3	B-4	63.20796608	0	0	0	0	0	0
141	3	B-4	31.60398304	0	0	0	0	0	0
142	3	B-4	31.60398304	0	0	0	0	0	0
143	3	C-6	328.1807665	0	0	0	0	0	0
144	3	C-8	222.1040313	0	0	0	0	0	0
145	3	C-12	168.6432343	0	0	0	0	0	0
146	3	C-6	328.1807665	0	0	0	0	0	0
147	3	C-8	222.1040313	0	0	0	0	0	0
148	3	C-12	168.6432343	0	0	0	0	0	0
149	3	Z-2	220.6020598	0	0	0	0	0	0
150	3	A-2	220.6020598	0	0	0	0	0	0
151	3	G-1.5	629.6076661	0	0	0	0	0	0
152	3	G-2.5	435.4778534	0	0	0	0	0	0
153	3	G-4	330.1051674	0	0	0	0	0	0
154	3	G-1.5	629.6076661	0	0	0	0	0	0
155	3	G-2.5	435.4778534	0	0	0	0	0	0
156	3	G-4	330.1051674	0	0	0	0	0	0
157	3	H-0.5	14.26872898	0	0	0	0	0	0
158	3	H-1	658.2859339	0	0	0	0	0	0
159	3	H-2	426.6068344	0	0	0	0	0	0
160	3	H-4	164.3720029	0	0	0	0	0	0
161	3	H-0.5	14.26872898	0	0	0	0	0	0
162	3	H-1	658.2859339	0	0	0	0	0	0
163	3	H-2	426.6068344	0	0	0	0	0	0
164	3	H-4	164.3720029	0	0	0	0	0	0
165	3	Q-0.5	38.24394859	0	0	0	0	0	0
166	3	Q-1	221.5971159	0	0	0	0	0	0
167	3	Q-2	112.8919307	0	0	0	0	0	0
168	3	Q-4	55.46029657	0	0	0	0	0	0
169	3	Q-0.5	38.24394859	0	0	0	0	0	0
170	3	Q-1	221.5971159	0	0	0	0	0	0
171	3	Q-2	112.8919307	0	0	0	0	0	0
172	3	Q-4	55.46029657	0	0	0	0	0	0
173	3	Q-0.5	38.24394859	0	0	0	0	0	0
174	3	Q-1	221.5971159	0	0	0	0	0	0
175	3	Q-2	112.8919307	0	0	0	0	0	0
176	3	Q-4	55.46029657	0	0	0	0	0	0
177	3	Q-0.5	38.24394859	0	0	0	0	0	0
178	3	Q-1	221.5971159	0	0	0	0	0	0
179	3	Q-2	112.8919307	0	0	0	0	0	0
180	3	Q-4	55.46029657	0	0	0	0	0	0
181	3	Q-0.5	38.24394859	0	0	0	0	0	0
182	3	Q-1	221.5971159	0	0	0	0	0	0
183	3	Q-2	112.8919307	0	0	0	0	0	0
184	3	Q-4	55.46029657	0	0	0	0	0	0
185	3	T-3	283.2154955	0	0	0	0	0	0
186	3	T-4	197.0398824	0	0	0	0	0	0
187	3	T-6	116.1211694	0	0	0	0	0	0
"""
PROJECT_TABLE_S4 = """
0	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
1	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
2	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
3	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
4	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
5	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
6	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
7	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
8	4	B-4	185.4920312	0	0	0.346666667	0.346666667	0.346666667	0.0588
9	4	B-4	92.7460156	0	0	0.346666667	0.346666667	0.346666667	0.0588
10	4	B-4	92.7460156	0	0	0.346666667	0.346666667	0.346666667	0.0588
11	4	C-6	963.0893184	0	0	0	0	0	0.06
12	4	C-8	651.7932859	0.0645	0.0645	0.151	0.151	0.151	0.08
13	4	C-12	494.9055951	0.079	0.079	0.245333333	0.245333333	0.245333333	0.12
14	4	C-6	963.0893184	0	0	0	0	0	0.06
15	4	C-8	651.7932859	0.0645	0.0645	0.151	0.151	0.151	0.08
16	4	C-12	494.9055951	0.079	0.079	0.245333333	0.245333333	0.245333333	0.12
17	4	Agir-0.5	25.39955239	6	0	0	0	0	0.14
18	4	Agir-2.5	766.6697864	1.2	0	0	0	0	0.04
19	4	Agir-5	485.7871007	2.5	0	0	0	0	0.06
20	4	Agir-8	200.3313937	4	0	0	0	0	0.096
21	4	Hakuryu-0.5	25.39955239	0	6	0	0	0	0.14
22	4	Hakuryu-2.5	766.6697864	0	1.2	0	0	0	0.04
23	4	Hakuryu-5	485.7871007	0	2.5	0	0	0	0.06
24	4	Hakuryu-8	200.3313937	0	4	0	0	0	0.096
25	4	Anchorage-0.5	25.39955239	0	0	9	0	0	0.14
26	4	Anchorage-2.5	766.6697864	0	0	2.25	0	0	0.04
27	4	Anchorage-5	485.7871007	0	0	3.75	0	0	0.06
28	4	Anchorage-8	200.3313937	0	0	6	0	0	0.096
29	4	August-0.5	25.39955239	0	0	0	9	0	0.14
30	4	August-2.5	766.6697864	0	0	0	2.25	0	0.04
31	4	August-5	485.7871007	0	0	0	3.75	0	0.06
32	4	August-8	200.3313937	0	0	0	6	0	0.096
33	4	Marcopolo-0.5	25.39955239	0	0	0	0	9	0.14
34	4	Marcopolo-2.5	766.6697864	0	0	0	0	2.25	0.04
35	4	Marcopolo-5	485.7871007	0	0	0	0	3.75	0.06
36	4	Marcopolo-8	200.3313937	0	0	0	0	6	0.096
37	4	Z-2	647.3855544	0	0	0	0	0	0.024
38	4	A-2	647.3855544	0	0	0	0	0	0.06
39	4	G-1.5	1847.665921	0.104	0.104	0.299	0.299	0.299	0.025
40	4	G-2.5	1277.966633	0.135	0.135	0.403333333	0.403333333	0.403333333	0.04
41	4	G-4	968.7367243	0.2585	0.2585	0.723333333	0.723333333	0.723333333	0.12
42	4	G-1.5	1847.665921	0.104	0.104	0.299	0.299	0.299	0.025
43	4	G-2.5	1277.966633	0.135	0.135	0.403333333	0.403333333	0.403333333	0.04
44	4	G-4	968.7367243	0.2585	0.2585	0.723333333	0.723333333	0.723333333	0.12
45	4	H-0.5	41.87344863	0.555	0.555	1.616666667	1.616666667	1.616666667	0
46	4	H-1	1931.826043	0.33	0.33	0.97	0.97	0.97	0
47	4	H-2	1251.933469	0.4765	0.4765	1.423333333	1.423333333	1.423333333	0
48	4	H-4	482.3711089	0.665	0.665	1.906666667	1.906666667	1.906666667	0
49	4	H-0.5	41.87344863	0.555	0.555	1.616666667	1.616666667	1.616666667	0
50	4	H-1	1931.826043	0.33	0.33	0.97	0.97	0.97	0
51	4	H-2	1251.933469	0.4765	0.4765	1.423333333	1.423333333	1.423333333	0
52	4	H-4	482.3711089	0.665	0.665	1.906666667	1.906666667	1.906666667	0
53	4	Q-0.5	112.2318616	0	0	0	0	0	0.34
54	4	Q-1	650.3056765	0	0	0	0	0	0.04
55	4	Q-2	331.2961139	0	0	0	0	0	0.08
56	4	Q-4	162.7554832	0	0	0	0	0	0.16
57	4	Q-0.5	112.2318616	0	0	0	0	0	0.34
58	4	Q-1	650.3056765	0	0	0	0	0	0.04
59	4	Q-2	331.2961139	0	0	0	0	0	0.08
60	4	Q-4	162.7554832	0	0	0	0	0	0.16
61	4	Q-0.5	112.2318616	0	0	0	0	0	0.34
62	4	Q-1	650.3056765	0	0	0	0	0	0.04
63	4	Q-2	331.2961139	0	0	0	0	0	0.08
64	4	Q-4	162.7554832	0	0	0	0	0	0.16
65	4	Q-0.5	112.2318616	0	0	0	0	0	0.34
66	4	Q-1	650.3056765	0	0	0	0	0	0.04
67	4	Q-2	331.2961139	0	0	0	0	0	0.08
68	4	Q-4	162.7554832	0	0	0	0	0	0.16
69	4	Q-0.5	112.2318616	0	0	0	0	0	0.34
70	4	Q-1	650.3056765	0	0	0	0	0	0.04
71	4	Q-2	331.2961139	0	0	0	0	0	0.08
72	4	Q-4	162.7554832	0	0	0	0	0	0.16
73	4	T-3	831.1328586	0	0	0	0	0	0.045
74	4	T-4	578.2392675	0	0	0	0	0	0.06
75	4	T-6	340.7727365	0	0	0	0	0	0.09
"""

"""
从 Alas (https://github.com/LmeSzinc/AzurLaneAutoScript) 里复制过来的一大堆代码
只是为了能单文件运行
"""


class cached_property:
    """缓存属性装饰器，属性仅计算一次并缓存到实例属性中。"""

    def __init__(self, func):
        """初始化缓存属性装饰器。

        Args:
            func (callable): 待计算的属性方法。
        """
        self.func = func

    def __get__(self, obj, cls):
        """获取属性值，若未计算则执行计算并缓存到实例属性字典中。

        Args:
            obj (object): 实例对象。
            cls (type): 实例所属类。

        Returns:
            Any: 属性计算值。
        """
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
        return value


def timer(function):
    """函数执行耗时计时器装饰器。

    Args:
        function (callable): 待计时的函数。

    Returns:
        callable: 装饰后的计时函数。
    """
    @wraps(function)
    def function_timer(*args, **kwargs):
        t0 = time.time()

        result = function(*args, **kwargs)
        t1 = time.time()
        print('%s: %s s' % (function.__name__, str(round(t1 - t0, 10))))
        return result

    return function_timer


class Filter:
    """通用对象过滤器与排序器。"""

    def __init__(self, regex, attr, preset=()):
        """初始化过滤器。

        Args:
            regex (str | re.Pattern): 匹配过滤器的正则表达式。
            attr (tuple[str, ...]): 提取的属性名称元组。
            preset (tuple[str, ...]): 内置预设字符串元组。
        """
        if isinstance(regex, str):
            regex = re.compile(regex)
        self.regex = regex
        self.attr = attr
        self.preset = tuple(list(p.lower() for p in preset))
        self.filter_raw = []
        self.filter = []

    def load(self, string):
        """加载并解析过滤器选择表达式。

        Args:
            string (str): 优先级表达式字符串（如 'A > B > C'）。
        """
        string = str(string)
        self.filter_raw = [f.strip(' \t\r\n') for f in string.split('>')]
        self.filter = [self.parse_filter(f) for f in self.filter_raw]

    def is_preset(self, filter):
        """判断是否为内置预设。

        Args:
            filter (str): 过滤器项。

        Returns:
            bool: 是否为预设。
        """
        return len(filter) and filter.lower() in self.preset

    def apply(self, objs, func=None):
        """对对象列表应用过滤规则并排序。

        Args:
            objs (list): 待过滤的对象与预设字符串列表。
            func (callable, optional): 自定义过滤函数，接收对象并返回 bool。

        Returns:
            list: 过滤与优先级排序后的对象列表。
        """
        out = []
        for raw, filter in zip(self.filter_raw, self.filter):
            if self.is_preset(raw):
                raw = raw.lower()
                if raw not in out:
                    out.append(raw)
            else:
                for index, obj in enumerate(objs):
                    if self.apply_filter_to_obj(obj=obj, filter=filter) and obj not in out:
                        out.append(obj)

        if func is not None:
            objs, out = out, []
            for obj in objs:
                if isinstance(obj, str):
                    out.append(obj)
                elif func(obj):
                    out.append(obj)
                else:
                    # 丢弃该对象
                    pass

        return out

    def apply_filter_to_obj(self, obj, filter):
        """检查单个对象是否满足过滤条件。

        Args:
            obj (object): 目标对象。
            filter (list[str | None]): 属性值过滤条件列表。

        Returns:
            bool: 是否满足条件。
        """
        for attr, value in zip(self.attr, filter):
            if not value:
                continue
            if str(obj.__getattribute__(attr)).lower() != str(value):
                return False

        return True

    def parse_filter(self, string):
        """解析单个过滤器选择子项。

        Args:
            string (str): 单项选择文本。

        Returns:
            list[str | None]: 提取的属性列表。
        """
        string = string.replace(' ', '').lower()
        result = re.search(self.regex, string)

        if self.is_preset(string):
            return [string]

        if result and len(string) and result.span()[1]:
            return [result.group(index + 1) for index, attr in enumerate(self.attr)]
        else:
            print(f'Invalid filter: "{string}". This selector does not match the regex, nor a preset.')
            # 无效过滤器将被忽略
            return ['1nVa1d'] + [None] * (len(self.attr) - 1)


class SelectedGrids:
    """项目与网格集合封装类。"""

    def __init__(self, grids):
        """初始化网格集合。

        Args:
            grids (list): 网格或项目对象列表。
        """
        self.grids = grids

    def __iter__(self):
        return iter(self.grids)

    def __getitem__(self, item):
        if isinstance(item, int):
            return self.grids[item]
        else:
            return SelectedGrids(self.grids[item])

    def __contains__(self, item):
        return item in self.grids

    def __str__(self):
        return '[' + ', '.join([str(grid) for grid in self]) + ']'

    def __len__(self):
        return len(self.grids)

    def __bool__(self):
        return self.count > 0

    @property
    def location(self):
        """获取所有网格的坐标列表。

        Returns:
            list[tuple]: 坐标元组列表。
        """
        return [grid.location for grid in self.grids]

    @property
    def cost(self):
        """获取所有网格的代价列表。

        Returns:
            list[int]: 代价值列表。
        """
        return [grid.cost for grid in self.grids]

    @property
    def weight(self):
        """获取所有网格的权重列表。

        Returns:
            list[int]: 权重值列表。
        """
        return [grid.weight for grid in self.grids]

    @property
    def count(self):
        """获取集合中元素数量。

        Returns:
            int: 元素总数。
        """
        return len(self.grids)

    def select(self, **kwargs):
        """按属性精确筛选集合中的对象。

        Args:
            **kwargs: 目标对象的属性值键值对。

        Returns:
            SelectedGrids: 筛选出的子集合。
        """
        result = []
        for grid in self:
            flag = True
            for k, v in kwargs.items():
                grid_v = grid.__getattribute__(k)
                if type(grid_v) != type(v) or grid_v != v:
                    flag = False
            if flag:
                result.append(grid)

        return SelectedGrids(result)

    def filter(self, func):
        """使用谓词函数过滤集合。

        Args:
            func (callable): 接收对象并返回布尔值的过滤函数。

        Returns:
            SelectedGrids: 过滤后的集合。
        """
        return SelectedGrids([grid for grid in self if func(grid)])

    def set(self, **kwargs):
        """为集合中的每个对象批量设置属性。

        Args:
            **kwargs: 待设置的属性键值对。
        """
        for grid in self:
            for key, value in kwargs.items():
                grid.__setattr__(key, value)

    def get(self, attr):
        """获取集合中所有对象的指定属性列表。

        Args:
            attr (str): 属性名称。

        Returns:
            list: 属性值列表。
        """
        return [grid.__getattribute__(attr) for grid in self.grids]

    def call(self, func, **kwargs):
        """调用集合中所有对象的同名方法。

        Args:
            func (str): 方法名称。
            **kwargs: 传递给方法的参数。

        Returns:
            list: 各对象方法调用的返回值列表。
        """
        return [grid.__getattribute__(func)(**kwargs) for grid in self]

    def add(self, grids):
        """合并两个集合（基于集合元素去重）。

        Args:
            grids (SelectedGrids): 待合并的集合。

        Returns:
            SelectedGrids: 合并后的集合。
        """
        return SelectedGrids(list(set(self.grids + grids.grids)))

    def add_by_eq(self, grids):
        """按相等性合并两个集合（基于 __eq__ 去重）。

        Args:
            grids (SelectedGrids): 待合并的集合。

        Returns:
            SelectedGrids: 合并后的集合。
        """
        new = []
        for grid in self.grids + grids.grids:
            if grid not in new:
                new.append(grid)

        return SelectedGrids(new)

    def intersect(self, grids):
        """计算两个集合的交集（基于 hash）。

        Args:
            grids (SelectedGrids): 目标集合。

        Returns:
            SelectedGrids: 交集结果。
        """
        return SelectedGrids(list(set(self.grids).intersection(set(grids.grids))))

    def intersect_by_eq(self, grids):
        """计算两个集合的交集（基于 __eq__）。

        Args:
            grids (SelectedGrids): 目标集合。

        Returns:
            SelectedGrids: 交集结果。
        """
        new = []
        for grid in self.grids:
            if grid in grids.grids:
                new.append(grid)

        return SelectedGrids(new)

    def delete(self, grids):
        """从当前集合中删除指定集合的元素。

        Args:
            grids (SelectedGrids | list): 待剔除的元素集合。

        Returns:
            SelectedGrids: 差集结果。
        """
        g = [grid for grid in self.grids if grid not in grids]
        return SelectedGrids(g)


def hr0(title):
    """打印一级标题横幅。

    Args:
        title (str): 标题文本。
    """
    middle = '|' + ' ' * 20 + title + ' ' * 20 + '|'
    border = '+' + '-' * (len(middle) - 2) + '+'
    print(border)
    print(middle)
    print(border)


def hr1(title):
    """打印等号分割标题。

    Args:
        title (str): 标题文本。
    """
    print('=' * 20 + ' ' + title + ' ' + '=' * 20)


def hr2(title):
    """打印短横线分割标题。

    Args:
        title (str): 标题文本。
    """
    print('-' * 20 + ' ' + title + ' ' + '-' * 20)


def hr3(title):
    """打印尖括号分割标题。

    Args:
        title (str): 标题文本。
    """
    print('<' * 3 + ' ' + title + ' ' + '>' * 3)


FILTER_REGEX = re.compile(r'([s!][123456789])?'
                          r'-?'
                          r'(neptune|monarch|ibuki|izumo|roon|saintlouis'
                          r'|seattle|georgia|kitakaze|azuma|friedrich'
                          r'|gascogne|champagne|cheshire|drake|mainz|odin'
                          r'|anchorage|hakuryu|agir|august|marcopolo'
                          r'|valparaiso|maximmelmann|duncan|takahashi|orage)?'
                          r'(dr|pry)?'
                          r'([bcdeghqtaz])?'
                          r'-?'
                          r'(\d.\d|\d\d?)?')
FILTER_ATTR = ('series', 'ship', 'ship_rarity', 'genre', 'duration')
FILTER_PRESET = ('shortest', 'cheapest', 'reset')
FILTER = Filter(FILTER_REGEX, FILTER_ATTR, FILTER_PRESET)

"""
科研优化器开始
"""


def parse_value(value):
    """解析字符串数值为 int、float 或保留原字符串。

    Args:
        value (str): 待解析文本。

    Returns:
        int | float | str: 解析后的值。
    """
    if '.' in value:
        try:
            return float(value)
        except ValueError:
            pass
    else:
        try:
            return int(value)
        except ValueError:
            pass
    return value


def parse_text_table(string, data_class):
    """解析制表符分隔的文本表格为对象集合。

    Args:
        string (str): 表格纯文本。
        data_class (type): 用于封装每行的数据类。

    Returns:
        SelectedGrids: 解析后的对象集合。
    """
    out = []
    for row in string.split('\n'):
        row = row.strip(' \r\n\t')
        if not len(row):
            continue
        row = row.split('\t')
        out.append(data_class(*row))
    return SelectedGrids(out)


@dataclass()
class Research:
    """储存每个科研项目的信息。"""
    index: int
    series: str
    name: str
    weight: float
    bp_Agir: float
    bp_Hakuryu: float
    bp_Anchorage: float
    bp_August: float
    bp_Marcopolo: float
    bp_Tenrai: float

    def __post_init__(self):
        # 转换变量类型
        for k, v in self.__dict__.items():
            self.__setattr__(k, parse_value(v))
        # 构造科研过滤器需要的对象属性
        self.genre, self.duration = self.name.split('-')
        self.duration = str(self.duration)
        if self.series == 4:
            self.series = f'S{TARGET_SERIES}'
        else:
            self.series = f'!{TARGET_SERIES}'
        if self.genre in BASE_SHIPS:
            self.ship = SHIP_NAME_MAP[self.genre]
            self.ship_rarity = 'dr' if self.ship in TARGET_DR_SHIPS else 'pry'
            self.genre = 'D'
        else:
            self.ship = ''
            self.ship_rarity = ''

    def __hash__(self):
        return hash(self.name)


PROJECTS = parse_text_table(PROJECT_TABLE, Research)
PROJECTS_S4 = parse_text_table(PROJECT_TABLE_S4, Research)


def product_dict(func):
    """为所有科研项目按 index 生成指定函数计算结果的映射字典。

    Args:
        func (callable): 处理 Research 对象的函数。

    Returns:
        dict[int, Any]: 项目索引到计算值的映射字典。
    """
    out = {}
    for project in PROJECTS:
        out[project.index] = func(project)
    return out


# 掉落加那么一点点，防止过滤器写错，100年都不毕业
PROJECT_DROP = product_dict(lambda project: np.array(
    [project.bp_Agir, project.bp_Hakuryu, project.bp_Anchorage, project.bp_August, project.bp_Marcopolo,
     project.bp_Tenrai]) + 0.000001)
PROJECT_DURATION = product_dict(lambda project: float(project.duration) / 24)
# 构造出掉落数据的数组，给numba
# Shape: (project_index=188, drop_items=6)
PROJECT_DROP_ARRAY = np.array(list(PROJECT_DROP.values()))
PROJECT_DURATION_ARRAY = np.array(list(PROJECT_DURATION.values()))


class ResearchPool:
    """科研项目池与选择优先级管理器。"""
    remove_projects = 'B > T > E'
    all_ships = TARGET_SHIPS

    def __init__(self, string):
        """初始化科研项目池。

        Args:
            string (str): 科研优先级过滤字符串。
        """
        FILTER.load(string)
        self.filter = SelectedGrids(FILTER.apply(PROJECTS.grids))
        self.reset_index = 1000
        for index, project in enumerate(self.filter):
            if str(project) == 'reset':
                self.reset_index = index
                break

    @cached_property
    def project_select_index(self):
        """将过滤器字符串转换为项目选择索引数组。

        Returns:
            np.ndarray: 形状为 (188,) 的索引数组，值越小表示优先级越高，1000 表示不选择。
        """
        out = np.ones((PROJECTS.count,), dtype=int) * 1000
        for index, project in enumerate(self.filter):
            if index != self.reset_index:
                out[project.index] = index

        FILTER.load(ResearchPool.remove_projects)
        projects = FILTER.apply(PROJECTS.grids)
        for project in projects:
            out[project.index] = 1000
        return out

    @classmethod
    def cal_project_spawn_rate(cls, projects):
        """计算不同完成条件下的出现概率。

        Args:
            projects (SelectedGrids): 科研项目集合。

        Returns:
            dict[int, np.ndarray]: 完成条件组合索引到项目出现概率分布的映射。
        """
        out = {}
        for condition in itertools.product([False, True], repeat=len(PROJECT_DROP[0])):
            ships = [ship for ship, con in zip(cls.all_ships, condition) if con]
            weight = np.array(projects.get('weight'))
            index = np.sum(np.array(condition) * [1, 2, 4, 8, 16, 32])
            remain = len(ships)
            if 0 < remain < 5:
                changed = []
                # 将所有四期船的概率增加到未完成的船上
                for ship in ships:
                    for project in projects.select(ship=ship):
                        weight[project.index] *= 5 / remain
                        changed.append(project.index)
                # 将已完成的科研船的定向概率归0
                for project in projects.select(genre='D'):
                    if project.index not in changed:
                        weight[project.index] = 0
            weight /= np.sum(weight)
            out[index] = weight
        return out


SPAWN_RATE = ResearchPool('reset').cal_project_spawn_rate(PROJECTS)
SPAWN_RATE_S4 = ResearchPool('reset').cal_project_spawn_rate(PROJECTS_S4)
# 构造出不同条件下的刷新概率数组，给numba
# 事先累加概率，加快 random_choice()
SPAWN_RATE = np.array([np.cumsum(SPAWN_RATE[n]) for n in range(64)])
SPAWN_RATE_S4 = np.array([np.cumsum(SPAWN_RATE_S4[n]) for n in range(64)])


@jit(nopython=True, fastmath=True)
def random_choice(size, possibility_cumsum):
    """numpy.random.choice() 的土法实现。

    因 numba 不支持带概率数组 p 参数的 numpy.random.choice()。
    https://numba.pydata.org/numba-doc/dev/reference/numpysupported.html

    Args:
        size (int): 抽样数量（仅支持生成一维数组）。
        possibility_cumsum (np.ndarray): 经过累加后的出现概率分布数组。

    Returns:
        np.ndarray: 抽样得到的索引数组。
    """
    rdm_unif = np.random.rand(size)
    return np.searchsorted(possibility_cumsum, rdm_unif)


@jit(nopython=True, fastmath=True)
def sample(condition, project_select_index, reset_index):
    """随机生成一组科研项目并根据优先级进行选择。

    Args:
        condition (np.ndarray): 形状为 (6,) 的各物品完成情况布尔数组。
        project_select_index (np.ndarray): 形状为 (188,) 的项目选择优先级数组，数值越小越优先，1000 表示不选择。
        reset_index (int): 刷新操作对应的优先级数值。

    Returns:
        tuple[int, int]: (有刷新时选择的项目索引, 无刷新时选择的项目索引)。
    """
    while 1:
        # 将完成情况转换成数组索引
        index = 0
        for i, c in enumerate(condition):
            if c:
                index += 2 ** i
        # 随机生成5个科研项目，包含3个四期，和2个任意
        # np.random.seed(3)
        p1, p2, p3 = random_choice(3, SPAWN_RATE_S4[index])
        p4, p5 = random_choice(2, SPAWN_RATE[index])
        # 去重
        if p1 == p4 or p2 == p4 or p3 == p4 or p1 == p5 or p2 == p5 or p3 == p5:
            continue
        # 加入刷新，1000表示刷新
        project_list = np.array([p1, p2, p3, p4, p5, 1000])
        # 将项目索引转换为过滤器索引
        f1, f2, f3, f4, f5 = np.take(project_select_index, project_list[:5])
        # print(filter_index)
        # print(project_list)

        # 无刷新时，选择的科研项目
        s_index = np.array([f1, f2, f3, f4, f5, 999])
        selected_no_reset = project_list[np.argmin(s_index)]
        # 有刷新时，选择的科研项目
        s_index = np.array([f1, f2, f3, f4, f5, reset_index])
        selected_with_reset = project_list[np.argmin(s_index)]

        return selected_with_reset, selected_no_reset


@jit(nopython=True, fastmath=True)
def events_add(rewards, condition):
    """模拟活动代币兑换蓝图对掉落进度的补充。

    Args:
        rewards (np.ndarray): 当前已获得的蓝图统计数组。
        condition (np.ndarray): 各蓝图未毕业状态数组。

    Returns:
        np.ndarray: 更新后的蓝图统计数组。
    """
    # 活动兑换蓝图给进度最慢的，有利于提高整体速度
    # 因为G系给的是随机的，早毕业的就溢出了，给进度最慢的不会溢出，就快了
    index = np.argmin(rewards[:2])
    rewards[index] += 0.5  # 每次活动约 15 张决战蓝图
    index = np.argmin(rewards[2:5])
    rewards[index + 2] += 1  # 每次活动约 30 张最高方案蓝图
    return rewards


@jit(nopython=True, fastmath=True)
def simulate(project_select_index, reset_index, target, active=1., interval=0.):
    """模拟一个玩家做科研到毕业的过程。

    Args:
        project_select_index (np.ndarray): 形状为 (188,) 的项目选择优先级数组，越小越优先，1000 表示不选择。
        reset_index (int): 刷新所对应的优先级数值。
        target (np.ndarray): 形状为 (6,) 的目标物品数量。
        active (float): 每日活跃时间（单位：天），超出活跃时间后仍在挂项目，但不再开始新项目。
        interval (float): 收菜延迟（单位：天），项目完成后隔多久才收获。

    Returns:
        tuple[float, np.ndarray]: (消耗总天数, 累计获得物品数组)。
    """
    rewards = np.array([0., 0., 0., 0., 0., 0.])
    condition = rewards != 0  # 每样物品是否达到目标数量，True未达到，False已达到
    has_reset = True
    day_cost = 0

    while 1:
        """
        做一个科研项目
        """
        while 1:
            index, index_no_reset = sample(condition, project_select_index, reset_index)
            # print(index, index_no_reset, has_reset)
            if has_reset:
                if index == 1000:
                    has_reset = False
                    continue
                else:
                    break
            else:
                if index_no_reset == 1000:
                    # 刷新次数用完，且需要刷新时，等到明天，使用明天的刷新次数
                    day_cost = int(day_cost) + 1
                    rewards = events_add(rewards, condition)
                    has_reset = False
                    continue
                else:
                    index = index_no_reset
                    break

        """
        收获科研项目，计算收益和消耗时间
        """
        prev_day = int(day_cost)
        rewards += PROJECT_DROP_ARRAY[index]
        day_cost += PROJECT_DURATION_ARRAY[index] + interval
        # print(rewards / day_cost)
        condition = rewards < target
        new_day = int(day_cost)
        new_hour = day_cost - new_day
        # 跨天重置刷新次数
        if new_day > prev_day:
            has_reset = True
            rewards = events_add(rewards, condition)
        else:
            # 超出活跃时间
            if new_hour > active:
                day_cost = int(day_cost) + 1
                has_reset = True
                rewards = events_add(rewards, condition)

        """
        达成目标物品数量
        """
        if not np.any(condition):
            break

    return day_cost, rewards


@jit(nopython=True, fastmath=True, parallel=True)
def simulate_many(project_select_index, reset_index, target, active, interval, sample_count):
    """并行多样本模拟，统计平均耗时与各物品产出。

    Args:
        project_select_index (np.ndarray): 项目选择优先级数组。
        reset_index (int): 刷新操作的优先级索引。
        target (np.ndarray): 毕业目标数量数组。
        active (float): 每日活跃时间（天）。
        interval (float): 收菜延迟（天）。
        sample_count (int): 模拟玩家总样本数。

    Returns:
        tuple[float, np.ndarray]: (平均消耗天数, 平均累计获得物品数组)。
    """
    day_cost_array = np.empty(sample_count)
    rewards_array = np.empty((sample_count, 6))
    for index in prange(sample_count):
        sim_day, sim_rewards = simulate(project_select_index, reset_index, target, active=active, interval=interval)
        day_cost_array[index] = sim_day
        rewards_array[index] = sim_rewards
    rewards = np.zeros(6)
    for index in range(sample_count):
        rewards += rewards_array[index]
    return np.mean(day_cost_array), rewards / sample_count


class FilterSimulator:
    """科研过滤器模拟器，用于评估过滤策略的毕业时间。"""
    active = 24 / 24
    interval = 0 / 60 / 24
    target = np.array([513, 513, 343, 343, 343, 150])

    def __init__(self, string):
        """初始化模拟器。

        Args:
            string (str): 待评估的过滤器字符串。
        """
        string = string.replace('E-315', 'A2')
        string = string.replace('E-031', 'Z2')
        self.string = string
        self.pool = ResearchPool(string)

    def run(self, sample_count=1000):
        """执行模拟并统计毕业耗时。

        Args:
            sample_count (int): 模拟样本数量，默认为 1000。

        Returns:
            float: 平均毕业天数。
        """
        if QUIET:
            day_cost, rewards = simulate_many(
                self.pool.project_select_index,
                self.pool.reset_index,
                FilterSimulator.target,
                FilterSimulator.active,
                FilterSimulator.interval,
                sample_count
            )
        else:
            day_cost = 0
            rewards = PROJECT_DROP[0] * 0
            for _ in tqdm(range(sample_count)):
                sim_day, sim_rewards = simulate(
                    self.pool.project_select_index,
                    self.pool.reset_index,
                    target=FilterSimulator.target,
                    active=FilterSimulator.active,
                    interval=FilterSimulator.interval
                )
                day_cost += sim_day
                rewards += sim_rewards
            day_cost /= sample_count
            rewards /= sample_count

        if not QUIET:
            hr3('End Testing')
            print(self.string)
            print(f'Average time cost: {day_cost}')
            print(f'Average rewards: {rewards}')

        return day_cost


def split_filter(string):
    """拆分过滤器字符串为项列表。

    Args:
        string (str | list[str]): 过滤器字符串或列表。

    Returns:
        list[str]: 拆分修剪后的子项列表。
    """
    if isinstance(string, list):
        return string
    return [f.strip(' \t\r\n') for f in string.split('>')]


def join_filter(selection):
    """将选择项列表连接为过滤器字符串。

    Args:
        selection (str | list[str]): 选择项列表。

    Returns:
        str: 用 ' > ' 连接后的字符串。
    """
    if isinstance(selection, str):
        return selection
    return ' > '.join(selection)


def beautify_filter(list_filter):
    """美化排版过滤器字符串。

    Args:
        list_filter (str | list[str]): 待排版的过滤器。

    Returns:
        str: 格式化换行后的过滤器字符串。
    """
    if isinstance(list_filter, str):
        list_filter = split_filter(list_filter)

    out = []
    length = 0
    for selection in list_filter:
        if length + len(selection) + 3 > 70:
            out.append('\n')
            length = 0
        out.append(selection)
        length += len(selection) + 3
    string = ' > '.join(out).strip('\n >').replace(' > \n', '\n').replace('\n ', '\n')
    return string


def position_change(string, position):
    """交换过滤器中相邻两个选项的位置。

    Args:
        string (str): 过滤器字符串。
        position (int): 待交换的索引位置。

    Returns:
        str: 交换后的过滤器字符串。
    """
    selection = split_filter(string)
    selection[position], selection[position + 1] = selection[position + 1], selection[position]
    return join_filter(selection)


def position_insert(string, insert, position):
    """向过滤器指定位置插入新选项。

    Args:
        string (str): 过滤器字符串。
        insert (str): 待插入的选项。
        position (int): 插入目标位置索引。

    Returns:
        str: 插入后的过滤器字符串。
    """
    selection = split_filter(string)
    selection.insert(position, insert)
    return join_filter(selection)


def epoch_worker(data):
    """单次迭代测试的子进程工作函数。

    Args:
        data (tuple): 包含索引、总数、样本量和过滤器字符串的测试元组。

    Returns:
        float: 模拟得到的平均毕业天数。
    """
    index, total, sample_count, select_index, forward_index, string = data
    if not QUIET:
        hr3(f'Start Testing: {index}/{total}')
    return FilterSimulator(string).run(sample_count)


class BruteForceOptimizer:
    """科研过滤器暴力搜索优化器。"""

    @timer
    def optimize(self, string, diff=10):
        """对过滤器进行多轮迭代优化，直至收敛。

        Args:
            string (str): 初始过滤器字符串。
            diff (float): 初始差异步长，默认为 10。
        """
        for epoch in range(100):
            hr0(f'Epoch: {epoch}')
            new, diff = self.epoch(string, diff=diff)
            if new == string:
                break
            else:
                string = new
                continue

    def gen(self, string, look_forward):
        """生成向前移动候选位置的变体序列。

        Args:
            string (str): 当前过滤器字符串。
            look_forward (int): 最大向前尝试移动的距离。

        Yields:
            tuple[int, int, str]: (选中项原索引, 相对前移距离, 变体过滤器字符串)。
        """
        string = split_filter(string)
        yield 0, 0, join_filter(string)

        for select_index, select_item in enumerate(string):
            string_dropped = [s for s in string if s != select_item]
            for forward_index in range(1, look_forward + 1):
                forward_index = select_index - forward_index
                if forward_index < 0:
                    continue
                string_added = deepcopy(string_dropped)
                string_added.insert(forward_index, select_item)
                string_added = join_filter(string_added)
                yield select_index, select_index - forward_index, string_added

    def epoch(self, string, diff=10):
        """执行单个优化周期的搜索与比较。

        Args:
            string (str): 当前周期的基准过滤器。
            diff (float): 前一轮的耗时改进差值。

        Returns:
            tuple[str, float]: (本轮产生的优化过滤器, 本轮获得的耗时缩短差值)。
        """
        diff = min(abs(diff), 1)
        level = np.log(diff) / np.log(10) + 1
        sample_count = int(np.power(10, 5 - level / 2))
        look_forward = int(np.power(3, level))
        look_forward = max(look_forward, 1)
        sample_count = min(max(sample_count, 10000), 300000)
        sample_count = int(os.environ.get('RESEARCH_OPTIMIZER_SAMPLE_COUNT', sample_count))
        look_forward = int(os.environ.get('RESEARCH_OPTIMIZER_LOOK_FORWARD', look_forward))
        print(f'diff: {diff}, look_forward: {look_forward}, sample_count: {sample_count}')

        string_split = split_filter(string)
        string_count = len(string_split)
        all_tests = list(self.gen(string, look_forward=look_forward))
        total = len(all_tests)
        # index, total, sample_count, select_index, forward_index, string_added
        tests_data = [(index, total, sample_count, *row) for index, row in enumerate(all_tests)]

        if BruteForceOptimizer.process <= 1:
            results = [epoch_worker(data) for data in tests_data]
        else:
            results = process_map(epoch_worker, tests_data, max_workers=BruteForceOptimizer.process)

        day_cost = np.ones((string_count, look_forward + 1)) * 1000
        for data, result in zip(tests_data[1:], results[1:]):
            day_cost[data[3]][data[4]] = result
        day_cost[:, 0] = results[0]

        hr2('Original filter')
        print(beautify_filter(string_split))

        hr2('Move forward')
        forward = np.argmin(day_cost, axis=1)
        if look_forward == 1:
            forward[np.min(day_cost, axis=1) != np.min(day_cost)] = 0
        for index, selection, forward_index in zip(range(len(forward)), string_split, forward):
            if index == 0:
                selection = '[Original]'
            print(f'{selection.ljust(12, " ")}forward: {forward_index}, day_cost: {day_cost[index][forward_index]}')
        diff = day_cost[0][0] - np.min(day_cost)
        print(f'diff: {diff}')

        hr2('New filter')
        forward[forward > 0] += 1
        forward = np.arange(forward.shape[0]) - forward
        new_index = np.argsort(forward)
        new_filter = beautify_filter([string_split[index] for index in new_index])
        print(new_filter)

        return new_filter, diff


"""
科研设置
"""
# 去除的科研项目
# 默认去除 B/T/E，因为掉落数据样本小
# 切魔方：'B > T > E'
# 只做0.5h魔方：'B > T > E > H1 > H2 > H4'
# 不切魔方：'B > T > E > H'
ResearchPool.remove_projects = 'B > T > H1 > H2 > H4'
# 每日活跃时间，按天计算
# 超出活跃时间后，仍在挂项目，但不再开始新项目
FilterSimulator.active = 24 / 24
# 收菜间隔，按天计算
# 项目完成后，过多长时间才收获
FilterSimulator.interval = 0 / 60 / 24
# 科研目标
# 需要的彩图纸 彩图纸 金图纸 金图纸 金图纸 彩装备 的物品数量
# 某种图纸数量满足后，不再产生该种定向科研，图纸全满后重置
# 四期毕业：np.array([513, 513, 343, 343, 343, 100])
# 仅科研船：np.array([513, 513, 343, 343, 343, 0])
# 仅天雷：np.array([0, 0, 0, 0, 0, 150])
FilterSimulator.target = np.array([513, 513, 343, 343, 343, 100])
# 运行的进程数
# 建议为cpu的物理进程数
BruteForceOptimizer.process = 6

if __name__ == '__main__':
    """
    这个文件包含模拟器和优化器两部分，取消注释对应的代码来运行
    Alas用户运行需要额外安装numba，无指定版本
    非Alas用户运行需要python>=3.7，安装 numba==0.45.1 llvmlite==0.29.0 numpy tqdm

    过滤器与Alas内的过滤器基本相同，编写参考 https://github.com/LmeSzinc/AzurLaneAutoScript/wiki/filter_string_cn
    但需要注意：
    - 必须有且只有一个reset
    - 不能使用Alas的预设选择，比如 shortest 需要展开成
      0.5 > 1 > 1.5 > 2 > 2.5 > 3 > 4 > 5 > 6 > 8 > 10 > 12
    - 选择数量建议为 10-24 个
      选择数量不能过少，否则毕业时间过长
      选择数量不能过多，否则优化太慢
    - 增加了 "!" 表示"非"逻辑，只能用在期数上
      比如 "!4" 表示非四期，详细参考正则表达式 FILTER_REGEX

    如果你在Alas的目录下运行，可以取消注释这些代码，把过程额外输出到log中
    """
    # from module.logger import logger
    # import builtins
    # builtins.print = logger.info
    """
    模拟大量用户使用同一个过滤器的平均毕业时间和毕业时获取物品的平均数量
    取消注释这些代码，将你的过滤器粘贴至这里，并运行，在8700k上需要约4.5分钟
    """
    # simulator = FilterSimulator("""
    # S4-DR0.5 > S4-PRY0.5 > S4-Q0.5 > S4-H0.5 > Q0.5 > S4-DR2.5
    # > S4-G1.5 > S4-Q1 > S4-DR5 > 0.5 > S4-G4 > S4-Q2 > S4-PRY2.5 > reset
    # > S4-DR8 > Q1 > 1 > S4-E-315 > S4-G2.5 > G1.5 > 1.5 > S4-E-031
    # > S4-Q4 > Q2 > E2 > 2 > DR2.5 > PRY2.5 > G2.5 > 2.5 > S4-PRY5
    # > S4-PRY8 > Q4 > G4 > 4 > S4-C6 > DR5 > PRY5 > 5 > C6 > 6 > S4-C8
    # > S4-C12 > DR8 > PRY8 > C8 > 8 > C12 > 12
    # """)
    # simulator.run(sample_count=300000)
    """
    优化一个过滤器，尝试调整过滤器选择的顺序，找到满足目标条件的消耗时间最短的排列方式
    类似于早期机器学习的实现，收敛过程中，向前尝试移动的距离变短，模拟样本量增大
    取消注释这些代码并运行，在8700k上需要约1-2天
    已给出一个包含所有选项、顺序大体正确的过滤器作为开始，不需要修改
    """
    optimizer = BruteForceOptimizer()
    optimizer.optimize("""
    S4-H0.5 > S4-DR0.5 > S4-PRY0.5 > S4-Q0.5 > !4-0.5 > S4-G1.5 > S4-Q1 > S4-DR2.5
    > S4-G4 > S4-Q4 > S4-DR5 > S4-DR8 > S4-Q2 > S4-PRY2.5 > S4-G2.5 > !4-1
    > S4-H1 > S4-H2 > S4-H4
    > S4-EP2 > S4-EB2
    > reset > S4-PRY8 > !4-1.5 > S4-PRY5 > !4-2.5 > !4-2 > !4-4
    > S4-C6 > !4-C8 > S4-C8 > !4-C6 > S4-C12 > !4-C12
    """, diff=1)
