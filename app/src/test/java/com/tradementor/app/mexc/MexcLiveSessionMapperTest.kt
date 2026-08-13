package com.tradementor.app.mexc

import com.tradementor.app.cloud.MexcCloudPosition
import com.tradementor.app.cloud.MexcCloudStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class MexcLiveSessionMapperTest {
    @Test fun maps_real_long_into_live_dashboard() {
        val state = MexcLiveSessionMapper.from(MexcCloudStatus(
            equity = 125.22,
            positions = listOf(MexcCloudPosition(
                side = "long", isolated = true, notionalUsd = 6.50,
                entryPrice = 64_900.0, markPrice = 65_100.0,
                unrealizedPnl = 0.02, liquidationPrice = 200.0,
                marginRatioPercent = 0.13,
            )),
        ))
        assertNotNull(state)
        assertEquals(6.50, state!!.session.longNotional, 0.0001)
        assertEquals(0.0, state.session.shortNotional, 0.0001)
        assertEquals(64_900.0, state.session.weightedEntry, 0.0001)
        assertEquals(0.13, state.marginRatioPercent, 0.0001)
        assertEquals(MexcPhase.LONG, state.session.phase)
    }

    @Test fun highest_margin_ratio_is_used_for_liquidation_monitor() {
        val state = MexcLiveSessionMapper.from(MexcCloudStatus(
            equity = 100.0,
            positions = listOf(
                MexcCloudPosition(side="long", notionalUsd=10.0, entryPrice=100.0, marginRatioPercent=12.0),
                MexcCloudPosition(side="short", notionalUsd=4.0, entryPrice=110.0, marginRatioPercent=72.0),
            ),
        ))
        assertEquals(72.0, state!!.marginRatioPercent, 0.0001)
        assertEquals(10.0, state.session.longNotional, 0.0001)
        assertEquals(4.0, state.session.shortNotional, 0.0001)
        assertEquals(MexcPhase.HEDGE, state.session.phase)
    }

    @Test fun no_position_returns_no_live_session() {
        assertEquals(null, MexcLiveSessionMapper.from(MexcCloudStatus(equity=125.0)))
    }
}
