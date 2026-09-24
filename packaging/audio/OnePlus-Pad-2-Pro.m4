# SPDX-License-Identifier: BSD-3-Clause
# Copyright, Linaro Ltd, 2023
# Graphs derived from the upstream SM8550-HDK AudioReach topology.
# Board microphone selection is provided by the codec routes and UCM.
include(`audioreach/audioreach.m4')
include(`audioreach/stream-subgraph.m4')
include(`audioreach/device-subgraph.m4')
include(`util/route.m4')
include(`util/mixer.m4')
include(`audioreach/tokens.m4')
include(`audioreach/module_tdm.m4')

# The hardware speaker interface carries eight discrete TDM slots.
# Stereo application routing and acoustic validation are separate from this graph.
STREAM_SG_PCM_ADD(audioreach/subgraph-stream-vol-playback.m4, FRONTEND_DAI_MULTIMEDIA1,
	`S32_LE', 48000, 48000, 8, 8,
	0x00004001, 0x00004001, 0x00006001, `110000')

STREAM_SG_PCM_ADD(audioreach/subgraph-stream-capture.m4, FRONTEND_DAI_MULTIMEDIA3,
	`S16_LE', 48000, 48000, 2, 2,
	0x00004003, 0x00004003, 0x00006020, `110000')

DEVICE_SG_ADD(audioreach/subgraph-device-codec-dma-capture.m4, `TX_CODEC_DMA_TX_3', TX_CODEC_DMA_TX_3,
	`S16_LE', 48000, 48000, 2, 2,
	LPAIF_INTF_TYPE_RXTX, CODEC_INTF_IDX_TX3, 0, DATA_FORMAT_FIXED_POINT,
	0x00004009, 0x00004009, 0x00006090)

STREAM_DEVICE_CAPTURE_MIXER(FRONTEND_DAI_MULTIMEDIA3, ``TX_CODEC_DMA_TX_3'')
STREAM_DEVICE_CAPTURE_ROUTE(FRONTEND_DAI_MULTIMEDIA3, ``MultiMedia3 Mixer'', ``TX_CODEC_DMA_TX_3, device120.logger1'')

# Secondary legacy TDM: LOG -> MFC -> hardware endpoint.
define(`NAME_PREFIX', `device40') dnl
AR_SUBGRAPH(1, SECONDARY_TDM_RX_0, 0x00004010,
	APM_SG_PERF_MODE_LOW_LATENCY, APM_SUB_GRAPH_DIRECTION_TX, APM_SUB_GRAPH_SID_AUDIO_PLAYBACK)
AR_CONTAINER(1, 0x00004010, APM_CONTAINER_TYPE_ID_GC, 8192,
	APM_CONT_GRAPH_POS_STREAM, APM_PROC_DOMAIN_ID_ADSP)
AR_MODULE_LOG(1, 1, 1, 0x00006100, 1, 1, 1, 2, 0x000019ab, 1, 0, 0x00006101)
AR_MODULE_MFC(1, 1, 1, 0x00006101, 1, 1, 1, 2, 0x00006102)
AR_MODULE_TDM_RX(1, 1, 1, 0x00006102, LPAIF_INTF_TYPE_LPAIF, I2S_INTF_TYPE_SECONDARY,
	DATA_FORMAT_FIXED_POINT, 0xff, 8, 32, 2, 1, 1, 0, 0, 0, `Secondary TDM0')

SectionGraph."Secondary TDM0 Hardware Graph" {
	index "1"
	lines [
		"device40.logger1, , Secondary TDM0 Audio Mixer"
		"device40.mfc1, , device40.logger1"
		"device40.tdm_rx1, , device40.mfc1"
		"Secondary TDM0 Playback, , device40.tdm_rx1"
	]
}
STREAM_DEVICE_PLAYBACK_MIXER(SECONDARY_TDM_RX_0, ``Secondary TDM0'', ``MultiMedia1'')
STREAM_DEVICE_PLAYBACK_ROUTE(SECONDARY_TDM_RX_0, ``Secondary TDM0 Audio Mixer'', ``MultiMedia1, stream0.logger1'')
