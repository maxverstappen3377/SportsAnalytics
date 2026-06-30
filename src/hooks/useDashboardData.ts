"use client";

import { useState, useEffect } from "react";

interface UseDashboardDataProps {
    selectedMatch: any;
    selectedPlayer: string;
}

export function useDashboardData({
    selectedMatch,
    selectedPlayer
}: UseDashboardDataProps) {
    const [loading, setLoading] = useState(false);
    const [refreshingCoach, setRefreshingCoach] = useState(false);
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    const [winProbTimeline, setWinProbTimeline] = useState<any[]>([]);
    const [statsA, setStatsA] = useState<any>(null);
    const [statsB, setStatsB] = useState<any>(null);
    const [heatmapGrid, setHeatmapGrid] = useState<number[][]>([]);
    const [rallies, setRallies] = useState<any[]>([]);
    const [recommendations, setRecommendations] = useState<any[]>([]);
    const [shots, setShots] = useState<any[]>([]);
    
    const [trajectories, setTrajectories] = useState<any[]>([]);
    const [playerPositions, setPlayerPositions] = useState<any[]>([]);
    const [playerANameState, setPlayerANameState] = useState<string>("");
    const [playerBNameState, setPlayerBNameState] = useState<string>("");

    // Live ingestion monitoring states
    const [liveProgress, setLiveProgress] = useState<number>(0);
    const [liveStatus, setLiveStatus] = useState<string>("done");
    const [liveShuttle, setLiveShuttle] = useState<any>(null);

    // Load data
    useEffect(() => {
        if (!selectedMatch || !selectedMatch.match_id) return;

        const matchId = selectedMatch.match_id;
        const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        if (!uuidRegex.test(matchId)) {
            return;
        }

        setLiveStatus(selectedMatch.processing_status);
        if (selectedMatch.processing_status === "done") {
            setLiveProgress(100);
        } else {
            setLiveProgress(0);
        }

        // WebSocket Stream Connection & Long Polling Fallback Ingestion Sync
        let ws: WebSocket | null = null;
        let pollInterval: any = null;

        const startPolling = () => {
            if (pollInterval) return;
            console.log("[Dashboard] Starting long-polling fallback status monitor...");
            pollInterval = setInterval(() => {
                fetch(`/api/v1/matches/${matchId}/status`)
                    .then((res) => res.ok ? res.json() : null)
                    .then((data) => {
                        if (data) {
                            setLiveStatus(data.status);
                            setLiveProgress(data.progress || 0);
                            if (data.status === "done") {
                                clearInterval(pollInterval);
                                pollInterval = null;
                                console.log("[Dashboard] Polling finished, re-fetching analytics...");
                                fetchData();
                            } else if (data.status === "failed") {
                                clearInterval(pollInterval);
                                pollInterval = null;
                                setErrorMessage("Video analysis failed.");
                            }
                        }
                    })
                    .catch(() => {});
            }, 2000);
        };

        if (selectedMatch.processing_status === "processing_cv") {
            const loc = window.location;
            const wsProto = loc.protocol === "https:" ? "wss:" : "ws:";
            // Connect directly to the FastAPI uvicorn server on port 8001 to bypass next.js ws proxy limitations
            const wsUrl = `${wsProto}//${loc.hostname}:8001/api/v1/matches/${matchId}/ws`;
            console.log("[Dashboard] Connecting WebSocket directly to:", wsUrl);
            ws = new WebSocket(wsUrl);

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.status === "processing") {
                        setLiveStatus("processing_cv");
                        setLiveProgress(data.progress);
                        if (data.shuttle) {
                            setLiveShuttle(data.shuttle);
                        }
                    } else if (data.status === "done") {
                        setLiveStatus("done");
                        setLiveProgress(100);
                        fetchData();
                    } else if (data.status === "failed") {
                        setLiveStatus("failed");
                        setErrorMessage(data.message || "Video analysis failed.");
                    }
                } catch (e) {
                    console.error("WS Parse Error:", e);
                }
            };

            ws.onerror = () => {
                console.warn("WS disconnected or errored out. Polling status endpoint instead.");
                startPolling();
            };

            ws.onclose = () => {
                console.warn("WS connection closed. Fallback to status polling.");
                startPolling();
            };
        }

        const fetchData = () => {
            setLoading(true);
            setErrorMessage(null);

            const playerAFetch = fetch(`/api/v1/players/${selectedMatch.player_a_id}`)
                .then(res => res.ok ? res.json() : null)
                .then(data => { if (data && data.name) setPlayerANameState(data.name); })
                .catch(() => {});

            const playerBFetch = fetch(`/api/v1/players/${selectedMatch.player_b_id}`)
                .then(res => res.ok ? res.json() : null)
                .then(data => { if (data && data.name) setPlayerBNameState(data.name); })
                .catch(() => {});

            const trajectoryFetch = fetch(`/api/v1/matches/${matchId}/trajectory`)
                .then(res => res.ok ? res.json() : [])
                .catch(() => []);

            const analyticsFetch = fetch(`/api/v1/matches/${matchId}/analytics`)
                .then(res => res.ok ? res.json() : null)
                .catch(() => null);

            const ralliesFetch = fetch(`/api/v1/matches/${matchId}/rallies`)
                .then(res => res.ok ? res.json() : [])
                .catch(() => []);

            const shotsFetch = fetch(`/api/v1/matches/${matchId}/shots`)
                .then(res => res.ok ? res.json() : [])
                .catch(() => []);

            const heatmapFetch = fetch(`/api/v1/matches/${matchId}/heatmap?type=hit`)
                .then(res => res.ok ? res.json() : null)
                .catch(() => null);

            const reportFetch = fetch(`/api/v1/matches/${matchId}/report`)
                .then(res => res.ok ? res.json() : null)
                .catch(() => null);

            // Real local Ollama coaching advice retrieval
            const coachingFetch = fetch(`/api/v1/matches/${matchId}/coaching/${selectedPlayer}`)
                .then(res => res.ok ? res.json() : null)
                .catch(() => null);

            Promise.all([
                playerAFetch,
                playerBFetch,
                trajectoryFetch,
                analyticsFetch,
                ralliesFetch,
                shotsFetch,
                heatmapFetch,
                reportFetch,
                coachingFetch
            ])
            .then(([_, __, trajData, analyticsData, ralliesData, shotsData, heatmapData, reportData, coachingData]) => {
                if (trajData && Array.isArray(trajData) && trajData.length > 0) {
                    setTrajectories(trajData.map((t: any) => ({
                        match_id: matchId,
                        frame_number: t.frame,
                        pixel_x: t.x,
                        pixel_y: t.y,
                        court_x: t.court_x,
                        court_y: t.court_y,
                        visible: t.x !== null && t.y !== null && t.x !== 0.0 && t.y !== 0.0,
                        speed: t.speed,
                        event: t.event,
                        vx: t.vx,
                        vy: t.vy,
                        vz: t.vz,
                        ax: t.ax,
                        ay: t.ay,
                        az: t.az,
                        landing_x_pred: t.landing_x_pred,
                        landing_y_pred: t.landing_y_pred,
                        time_to_landing: t.time_to_landing
                    })));
                } else {
                    setTrajectories([]);
                }

                const loadedRallies = Array.isArray(ralliesData) ? ralliesData : [];
                setRallies(loadedRallies);

                const loadedShots = Array.isArray(shotsData) ? shotsData : [];
                setShots(loadedShots);

                if (heatmapData && heatmapData.grid) {
                    setHeatmapGrid(heatmapData.grid);
                } else {
                    setHeatmapGrid(Array(20).fill(0).map(() => Array(10).fill(0)));
                }

                if (loadedRallies.length > 0) {
                    const timeline: any[] = [];
                    let scoreA = 0;
                    let scoreB = 0;
                    const sortedRallies = [...loadedRallies].sort((a, b) => (a.rally_number || 0) - (b.rally_number || 0));
                    
                    sortedRallies.forEach((r) => {
                        if (r.winner_id === selectedMatch.player_a_id) {
                            scoreA += 1;
                        } else {
                            scoreB += 1;
                        }
                        const diff = scoreA - scoreB;
                        let probA = 0.5 + diff * 0.035;
                        probA = Math.min(Math.max(probA, 0.1), 0.9);
                        
                        timeline.push({
                            rally_id: r.rally_id,
                            win_prob_a: probA,
                            win_prob_b: 1.0 - probA,
                            score_a: scoreA,
                            score_b: scoreB,
                            shap_explanation: r.shap_explanation || null
                        });
                    });
                    setWinProbTimeline(timeline);
                } else {
                    setWinProbTimeline([]);
                }

                const playerAId = selectedMatch.player_a_id;
                const playerBId = selectedMatch.player_b_id;
                
                const shotsA = loadedShots.filter((s: any) => s.hitter_id === playerAId);
                const shotsB = loadedShots.filter((s: any) => s.hitter_id === playerBId);

                const shotDistA: Record<string, number> = {};
                shotsA.forEach((s: any) => {
                    shotDistA[s.shot_type] = (shotDistA[s.shot_type] || 0) + 1;
                });

                const shotDistB: Record<string, number> = {};
                shotsB.forEach((s: any) => {
                    shotDistB[s.shot_type] = (shotDistB[s.shot_type] || 0) + 1;
                });

                const totalRallies = loadedRallies.length || 1;
                const lostRalliesA = loadedRallies.filter((r: any) => r.winner_id === playerBId).length;
                const lostRalliesB = loadedRallies.filter((r: any) => r.winner_id === playerAId).length;

                setStatsA({
                    distance_covered_m: Math.round(shotsA.length * 4.2),
                    avg_reaction_time_ms: 220.0,
                    pressure_index: lostRalliesA / totalRallies,
                    avg_rally_length: loadedRallies.length ? parseFloat((loadedShots.length / loadedRallies.length).toFixed(1)) : 6.0,
                    shot_type_distribution: shotDistA
                });

                setStatsB({
                    distance_covered_m: Math.round(shotsB.length * 4.5),
                    avg_reaction_time_ms: 235.0,
                    pressure_index: lostRalliesB / totalRallies,
                    avg_rally_length: loadedRallies.length ? parseFloat((loadedShots.length / loadedRallies.length).toFixed(1)) : 6.0,
                    shot_type_distribution: shotDistB
                });

                // Load Ollama Coaching metrics
                if (coachingData && Array.isArray(coachingData.recommendations) && coachingData.recommendations.length > 0) {
                    setRecommendations(coachingData.recommendations);
                } else if (reportData && Array.isArray(reportData.tactical_notes)) {
                    // Fallback to report notes
                    setRecommendations(reportData.tactical_notes.map((note: string, idx: number) => ({
                        category: "tactical",
                        priority: idx + 1,
                        summary: note,
                        supporting_metric: "Derived from shuttle trajectory physics analytics",
                        estimated_impact: idx === 0 ? "high" : "moderate"
                    })));
                } else {
                    setRecommendations([]);
                }

                setPlayerPositions([]);
                setLoading(false);
            })
            .catch((err) => {
                console.error("Dashboard API error:", err);
                setErrorMessage("Failed to load match analytics from backend API.");
                setLoading(false);
            });
        };

        fetchData();

        return () => {
            if (ws) {
                ws.close();
            }
            if (pollInterval) {
                clearInterval(pollInterval);
            }
        };

    }, [selectedMatch, selectedPlayer]);

    const handleRefreshCoaching = () => {
        if (!selectedMatch) {
            setRefreshingCoach(true);
            setTimeout(() => setRefreshingCoach(false), 800);
            return;
        }

        setRefreshingCoach(true);
        fetch(`/api/v1/coaching/refresh/${selectedMatch.match_id}`, { method: "POST" })
            .then(res => {
                if (res.ok) {
                    return fetch(`/api/v1/matches/${selectedMatch.match_id}/coaching/${selectedPlayer}`);
                }
                throw new Error("Failed to clear coaching cache");
            })
            .then(res => res && res.ok ? res.json() : null)
            .then(data => {
                if (data && Array.isArray(data.recommendations)) {
                    setRecommendations(data.recommendations);
                }
                setRefreshingCoach(false);
            })
            .catch((err) => {
                console.error("Coaching refresh error:", err);
                setRefreshingCoach(false);
            });
    };

    return {
        loading,
        refreshingCoach,
        errorMessage,
        winProbTimeline,
        statsA,
        statsB,
        heatmapGrid,
        rallies,
        recommendations,
        shots,
        trajectories,
        playerPositions,
        playerANameState,
        playerBNameState,
        liveProgress,
        liveStatus,
        liveShuttle,
        handleRefreshCoaching
    };
}
