"use client";

import React, { useState, useEffect, useRef } from "react";
import { Sparkles, AlertCircle } from "lucide-react";

import CourtHeatmap from "../components/CourtHeatmap";
import MatchIngestionPanel from "../components/MatchIngestionPanel";
import { useDashboardData } from "../hooks/useDashboardData";

const projectCourtToVideo = (courtX: number | null | undefined, courtY: number | null | undefined) => {
    if (courtX === null || courtX === undefined || courtY === null || courtY === undefined) {
        return null;
    }
    const y = 30 + courtY * (92 - 30);
    const widthAtY = 30 + courtY * (76 - 30);
    const minXAtY = 35 - courtY * (35 - 12);
    const x = minXAtY + courtX * widthAtY;
    return { x: `${x}%`, y: `${y}%` };
};

export default function Dashboard() {
    const [matches, setMatches] = useState<any[]>([]);
    const [selectedMatch, setSelectedMatch] = useState<any>(null);
    const [selectedPlayer, setSelectedPlayer] = useState<string>("");
    const [allPlayers, setAllPlayers] = useState<any[]>([]);

    const [heatmapTypes, setHeatmapTypes] = useState<string[]>(["hit", "landing"]);
    const [shotFilter, setShotFilter] = useState<string>("All Shots");
    const [showUploadForm, setShowUploadForm] = useState(true);
    
    const [playbackMs, setPlaybackMs] = useState(0);
    const [activeShuttle, setActiveShuttle] = useState<any>(null);
    const [activeShuttlePos, setActiveShuttlePos] = useState<{ x: string; y: string } | null>(null);
    
    const videoRef = useRef<HTMLVideoElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const [showSkeleton, setShowSkeleton] = useState(true);
    const [showSpeedTrail, setShowSpeedTrail] = useState(true);
    const [showMiniMap, setShowMiniMap] = useState(true);
    const [highlightedFrame, setHighlightedFrame] = useState<number | null>(null);

    // Load matches list on mount
    useEffect(() => {
        fetch("/api/v1/matches")
            .then(res => res.ok ? res.json() : [])
            .then(data => {
                if (data && data.length > 0) {
                    setMatches(data);
                    setSelectedMatch(data[0]);
                    setSelectedPlayer(data[0].player_a_id);
                } else {
                    const defaultMatch = {
                        match_id: "00000000-0000-0000-0000-000000000000",
                        player_a_id: "00000000-0000-0000-0000-000000000001",
                        player_b_id: "00000000-0000-0000-0000-000000000002",
                        tournament: "All England Open 2026 (Demo)",
                        match_date: "2026-03-15",
                        video_uri: "https://assets.mixkit.co/videos/preview/mixkit-badminton-player-hitting-shuttlecock-40019-large.mp4",
                        processing_status: "done",
                        fps: 30.0
                    };
                    setMatches([defaultMatch]);
                    setSelectedMatch(defaultMatch);
                    setSelectedPlayer(defaultMatch.player_a_id);
                }
            })
            .catch(() => {
                const defaultMatch = {
                    match_id: "00000000-0000-0000-0000-000000000000",
                    player_a_id: "00000000-0000-0000-0000-000000000001",
                    player_b_id: "00000000-0000-0000-0000-000000000002",
                    tournament: "All England Open 2026 (Demo)",
                    match_date: "2026-03-15",
                    video_uri: "https://assets.mixkit.co/videos/preview/mixkit-badminton-player-hitting-shuttlecock-40019-large.mp4",
                    processing_status: "done",
                    fps: 30.0
                };
                setMatches([defaultMatch]);
                setSelectedMatch(defaultMatch);
                setSelectedPlayer(defaultMatch.player_a_id);
            });
    }, []);

    // Load players list on mount
    useEffect(() => {
        fetch("/api/v1/players")
            .then(res => res.ok ? res.json() : [])
            .then(data => {
                if (data && Array.isArray(data) && data.length > 0) {
                    setAllPlayers(data);
                } else {
                    setAllPlayers([
                        { player_id: "00000000-0000-0000-0000-000000000001", name: "Viktor Axelsen" },
                        { player_id: "00000000-0000-0000-0000-000000000002", name: "Lee Zii Jia" }
                    ]);
                }
            })
            .catch(() => {
                setAllPlayers([
                    { player_id: "00000000-0000-0000-0000-000000000001", name: "Viktor Axelsen" },
                    { player_id: "00000000-0000-0000-0000-000000000002", name: "Lee Zii Jia" }
                ]);
            });
    }, []);

    const {
        loading,
        errorMessage,
        heatmapGrid,
        shots,
        trajectories,
        playerPositions,
        liveProgress,
        liveStatus,
        liveShuttle
    } = useDashboardData({
        selectedMatch,
        selectedPlayer
    });

    // Canvas overlay drawing loop
    useEffect(() => {
        let rVFCId: number;
        let animId: number;
        
        const projectCourtToCanvas = (courtX: number, courtY: number, video: HTMLVideoElement, canvas: HTMLCanvasElement) => {
            const y = 30 + courtY * (92 - 30);
            const widthAtY = 30 + courtY * (76 - 30);
            const minXAtY = 35 - courtY * (35 - 12);
            const x = minXAtY + courtX * widthAtY;
            return {
                x: (x / 100) * canvas.width,
                y: (y / 100) * canvas.height
            };
        };

        const detectImpacts = (trajs: any[]) => {
            const impacts: { x: number; y: number; frame: number; isOut: boolean }[] = [];
            if (trajs.length < 3) return impacts;
            
            for (let i = 1; i < trajs.length - 1; i++) {
                const prev = trajs[i - 1];
                const curr = trajs[i];
                const next = trajs[i + 1];
                
                if (prev.pixel_y && curr.pixel_y && next.pixel_y && prev.visible && curr.visible && next.visible) {
                    const isLocalMaxY = curr.pixel_y > prev.pixel_y && curr.pixel_y > next.pixel_y;
                    const dy1 = curr.pixel_y - prev.pixel_y;
                    const dy2 = next.pixel_y - curr.pixel_y;
                    const isAbruptFlip = dy1 * dy2 < -5;
                    const isLabeledEvent = curr.event !== null && curr.event !== undefined && curr.event !== "rally" && curr.event !== "";
                    
                    if ((isLocalMaxY && isAbruptFlip) || isLabeledEvent) {
                        const inBounds = curr.court_x >= 0.05 && curr.court_x <= 0.95 && curr.court_y >= 0.05 && curr.court_y <= 0.95;
                        impacts.push({
                            x: curr.pixel_x,
                            y: curr.pixel_y,
                            frame: curr.frame_number,
                            isOut: !inBounds
                        });
                    }
                }
            }
            return impacts;
        };

        const drawOverlay = (timeSec?: number) => {
            const video = videoRef.current;
            const canvas = canvasRef.current;
            if (!video || !canvas) return;

            const ctx = canvas.getContext("2d");
            if (!ctx) return;

            const rect = video.getBoundingClientRect();
            if (canvas.width !== rect.width || canvas.height !== rect.height) {
                canvas.width = rect.width;
                canvas.height = rect.height;
            }
            
            ctx.clearRect(0, 0, canvas.width, canvas.height);

            const mediaTime = timeSec !== undefined ? timeSec : video.currentTime;
            const currentFrame = Math.round(mediaTime * (selectedMatch?.fps || 30.0));

            // 1. Draw speed trail (if showSpeedTrail)
            if (showSpeedTrail && trajectories.length > 0) {
                const startFrame = Math.max(0, currentFrame - 15);
                ctx.beginPath();
                let first = true;
                for (let f = startFrame; f <= currentFrame; f++) {
                    const pt = trajectories.find(t => t.frame_number === f);
                    if (pt && pt.pixel_x !== null && pt.pixel_y !== null && pt.pixel_x !== 0.0 && pt.pixel_y !== 0.0) {
                        const canvasX = (pt.pixel_x / video.videoWidth) * canvas.width;
                        const canvasY = (pt.pixel_y / video.videoHeight) * canvas.height;
                        if (first) {
                            ctx.moveTo(canvasX, canvasY);
                            first = false;
                        } else {
                            ctx.lineTo(canvasX, canvasY);
                        }
                    }
                }
                ctx.strokeStyle = "rgba(234, 179, 8, 0.65)";
                ctx.lineWidth = 3;
                ctx.stroke();
            }

            // Draw pulsing neon circle centered precisely over the ball/shuttlecock's (x,y) coordinates
            const shPt = trajectories.find(t => t.frame_number === currentFrame);
            if (shPt && shPt.pixel_x !== null && shPt.pixel_y !== null && shPt.pixel_x > 0) {
                const canvasX = (shPt.pixel_x / video.videoWidth) * canvas.width;
                const canvasY = (shPt.pixel_y / video.videoHeight) * canvas.height;
                
                const pulsePeriod = 500;
                const nowTime = Date.now();
                const scale = 1 + 0.3 * Math.sin((nowTime % pulsePeriod) / pulsePeriod * 2 * Math.PI);
                const radius = 8 * scale;
                
                ctx.beginPath();
                ctx.arc(canvasX, canvasY, radius, 0, 2 * Math.PI);
                ctx.fillStyle = "rgba(56, 189, 248, 0.4)";
                ctx.fill();
                
                ctx.beginPath();
                ctx.arc(canvasX, canvasY, 4, 0, 2 * Math.PI);
                ctx.fillStyle = "#38bdf8";
                ctx.fill();
                ctx.strokeStyle = "#ffffff";
                ctx.lineWidth = 1.5;
                ctx.stroke();
                
                if (shPt.speed) {
                    ctx.fillStyle = "#38bdf8";
                    ctx.font = "bold 10px monospace";
                    ctx.textAlign = "left";
                    ctx.fillText(`${shPt.speed.toFixed(1)} km/h`, canvasX + 12, canvasY - 4);
                }
            }

            // Draw Persistent Glowing Markers for Bounces/Impacts
            const impacts = detectImpacts(trajectories);
            impacts.forEach(imp => {
                if (currentFrame >= imp.frame) {
                    const canvasX = (imp.x / video.videoWidth) * canvas.width;
                    const canvasY = (imp.y / video.videoHeight) * canvas.height;
                    
                    ctx.beginPath();
                    ctx.arc(canvasX, canvasY, 12, 0, 2 * Math.PI);
                    ctx.fillStyle = imp.isOut ? "rgba(239, 68, 68, 0.25)" : "rgba(16, 185, 129, 0.25)";
                    ctx.fill();
                    
                    ctx.beginPath();
                    ctx.arc(canvasX, canvasY, 5, 0, 2 * Math.PI);
                    ctx.fillStyle = imp.isOut ? "#ef4444" : "#10b981";
                    ctx.fill();
                    ctx.strokeStyle = "#ffffff";
                    ctx.lineWidth = 1.5;
                    ctx.stroke();
                    
                    ctx.fillStyle = "#ffffff";
                    ctx.font = "bold 8px sans-serif";
                    ctx.textAlign = "center";
                    ctx.fillText(imp.isOut ? "OUT" : "IN", canvasX, canvasY - 8);
                }
            });

            // 2. Draw Minimalist Skeletal Overlay (if showSkeleton)
            if (showSkeleton && playerPositions && playerPositions.length > 0) {
                const currentPos = playerPositions.filter(p => p.frame === currentFrame);
                currentPos.forEach((p, pIdx) => {
                    if (p.pose_keypoints) {
                        const kpDict = p.pose_keypoints;
                        const color = pIdx === 0 ? "rgba(99, 102, 241, 0.85)" : "rgba(244, 63, 94, 0.85)";
                        
                        const connections = [
                            ["left_shoulder", "left_elbow"], ["left_elbow", "left_wrist"],
                            ["right_shoulder", "right_elbow"], ["right_elbow", "right_wrist"],
                            ["left_shoulder", "right_shoulder"], ["left_shoulder", "left_hip"],
                            ["right_shoulder", "right_hip"], ["left_hip", "right_hip"],
                            ["left_hip", "left_knee"], ["left_knee", "left_ankle"],
                            ["right_hip", "right_knee"], ["right_knee", "right_ankle"]
                        ];
                        
                        ctx.beginPath();
                        connections.forEach(([sName, eName]) => {
                            const start = kpDict[sName];
                            const end = kpDict[eName];
                            if (start && end && start.score > 0.3 && end.score > 0.3) {
                                const sx = (start.x / video.videoWidth) * canvas.width;
                                const sy = (start.y / video.videoHeight) * canvas.height;
                                const ex = (end.x / video.videoWidth) * canvas.width;
                                const ey = (end.y / video.videoHeight) * canvas.height;
                                ctx.moveTo(sx, sy);
                                ctx.lineTo(ex, ey);
                            }
                        });
                        ctx.strokeStyle = color;
                        ctx.lineWidth = 1.5;
                        ctx.stroke();
                        
                        const joints = ["left_wrist", "right_wrist", "left_ankle", "right_ankle", "left_hip", "right_hip"];
                        joints.forEach(jName => {
                            const pt = kpDict[jName];
                            if (pt && pt.score > 0.3) {
                                const jx = (pt.x / video.videoWidth) * canvas.width;
                                const jy = (pt.y / video.videoHeight) * canvas.height;
                                ctx.beginPath();
                                ctx.arc(jx, jy, 3.5, 0, 2 * Math.PI);
                                ctx.fillStyle = "#ffffff";
                                ctx.fill();
                                ctx.strokeStyle = color;
                                ctx.lineWidth = 1.5;
                                ctx.stroke();
                            }
                        });
                        
                        if (p.com_x !== null && p.com_y !== null) {
                            const comProj = projectCourtToCanvas(p.com_x, p.com_y, video, canvas);
                            ctx.beginPath();
                            ctx.arc(comProj.x, comProj.y, 5, 0, 2 * Math.PI);
                            ctx.fillStyle = "rgba(16, 185, 129, 0.9)";
                            ctx.fill();
                            ctx.strokeStyle = "#ffffff";
                            ctx.lineWidth = 1;
                            ctx.stroke();
                        }
                    }
                });
            }

            // 3. Draw PiP Mini-Map (if showMiniMap)
            if (showMiniMap && playerPositions) {
                const mapW = 120;
                const mapH = 200;
                const mapX = canvas.width - mapW - 15;
                const mapY = 15;
                
                ctx.fillStyle = "rgba(10, 10, 10, 0.75)";
                ctx.fillRect(mapX, mapY, mapW, mapH);
                ctx.strokeStyle = "rgba(255, 255, 255, 0.3)";
                ctx.lineWidth = 1;
                ctx.strokeRect(mapX, mapY, mapW, mapH);
                
                ctx.beginPath();
                ctx.moveTo(mapX, mapY + mapH / 2);
                ctx.lineTo(mapX + mapW, mapY + mapH / 2);
                ctx.strokeStyle = "rgba(255, 255, 255, 0.6)";
                ctx.stroke();
                
                const currentPos = playerPositions.filter(p => p.frame === currentFrame);
                currentPos.forEach((p, pIdx) => {
                    if (p.court_x !== null && p.court_y !== null) {
                        const dotX = mapX + p.court_x * mapW;
                        const dotY = mapY + p.court_y * mapH;
                        ctx.beginPath();
                        ctx.arc(dotX, dotY, 4, 0, 2 * Math.PI);
                        ctx.fillStyle = pIdx === 0 ? "#6366f1" : "#f43f5e";
                        ctx.fill();
                        
                        if (p.predicted_x_05s !== null && p.predicted_y_05s !== null) {
                            const predX = mapX + p.predicted_x_05s * mapW;
                            const predY = mapY + p.predicted_y_05s * mapH;
                            ctx.beginPath();
                            ctx.moveTo(dotX, dotY);
                            ctx.lineTo(predX, predY);
                            ctx.strokeStyle = "rgba(234, 179, 8, 0.8)";
                            ctx.lineWidth = 1;
                            ctx.stroke();
                        }
                    }
                });
                
                const shPtMini = trajectories.find(t => t.frame_number === currentFrame);
                if (shPtMini && shPtMini.court_x !== null && shPtMini.court_y !== null) {
                    const shX = mapX + shPtMini.court_x * mapW;
                    const shY = mapY + shPtMini.court_y * mapH;
                    ctx.beginPath();
                    ctx.arc(shX, shY, 3, 0, 2 * Math.PI);
                    ctx.fillStyle = "#eab308";
                    ctx.fill();
                }
            }
        };

        const updateFrame = (now: number, metadata: any) => {
            drawOverlay(metadata.mediaTime);
            if (videoRef.current && 'requestVideoFrameCallback' in videoRef.current) {
                // @ts-ignore
                rVFCId = videoRef.current.requestVideoFrameCallback(updateFrame);
            }
        };

        if (videoRef.current && 'requestVideoFrameCallback' in videoRef.current) {
            // @ts-ignore
            rVFCId = videoRef.current.requestVideoFrameCallback(updateFrame);
        } else {
            const loop = () => {
                if (videoRef.current) {
                    drawOverlay(videoRef.current.currentTime);
                }
                animId = requestAnimationFrame(loop);
            };
            animId = requestAnimationFrame(loop);
        }
        
        return () => {
            if (videoRef.current && 'requestVideoFrameCallback' in videoRef.current && rVFCId) {
                // @ts-ignore
                videoRef.current.cancelVideoFrameCallback(rVFCId);
            }
            if (animId) {
                cancelAnimationFrame(animId);
            }
        };
    }, [trajectories, playerPositions, showSkeleton, showSpeedTrail, showMiniMap, selectedMatch]);

    const handleSeek = (ms: number) => {
        setPlaybackMs(ms);
        if (videoRef.current) {
            videoRef.current.currentTime = ms / 1000;
            videoRef.current.play().catch(() => {});
        }
    };

    const handleContainerClick = (e: React.MouseEvent<HTMLDivElement>) => {
        const canvas = canvasRef.current;
        const video = videoRef.current;
        if (!canvas || !video || trajectories.length === 0) return;
        
        const rect = e.currentTarget.getBoundingClientRect();
        const clickX = e.clientX - rect.left;
        const clickY = e.clientY - rect.top;
        
        // Pass click through to video controls if clicked in the bottom controls bar area (15% height)
        if (clickY > rect.height * 0.85) {
            return;
        }
        
        let closestPt: any = null;
        let minDistance = Infinity;
        
        trajectories.forEach(pt => {
            if (pt.pixel_x !== null && pt.pixel_y !== null) {
                const cx = (pt.pixel_x / video.videoWidth) * canvas.width;
                const cy = (pt.pixel_y / video.videoHeight) * canvas.height;
                const dist = Math.sqrt((cx - clickX) ** 2 + (cy - clickY) ** 2);
                if (dist < minDistance) {
                    minDistance = dist;
                    closestPt = pt;
                }
            }
        });
        
        if (closestPt && minDistance < 40) {
            const computedTime = closestPt.frame_number / (selectedMatch?.fps || 30.0);
            video.currentTime = computedTime;
            setPlaybackMs(computedTime * 1000);
            setHighlightedFrame(closestPt.frame_number);
            
            const rowEl = document.getElementById(`row-${closestPt.frame_number}`);
            if (rowEl) {
                rowEl.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        } else {
            // General click plays/pauses the video cleanly
            if (video.paused) {
                video.play().catch(() => {});
            } else {
                video.pause();
            }
        }
    };

    const handleTimeUpdate = (e: React.SyntheticEvent<HTMLVideoElement>) => {
        const video = e.currentTarget;
        const currentMs = video.currentTime * 1000;
        setPlaybackMs(currentMs);

        const currentFrame = Math.round((currentMs / 1000) * (selectedMatch?.fps || 30.0));
        const shuttlePoint = trajectories.find(t => t.frame_number === currentFrame && t.visible);
        if (shuttlePoint) {
            setActiveShuttle({ court_x: shuttlePoint.court_x, court_y: shuttlePoint.court_y });
            if (shuttlePoint.pixel_x && shuttlePoint.pixel_y) {
                const xPct = (shuttlePoint.pixel_x / video.videoWidth) * 100 || (shuttlePoint.pixel_x / 640) * 100;
                const yPct = (shuttlePoint.pixel_y / video.videoHeight) * 100 || (shuttlePoint.pixel_y / 360) * 100;
                setActiveShuttlePos({ x: `${xPct}%`, y: `${yPct}%` });
            } else {
                setActiveShuttlePos(projectCourtToVideo(shuttlePoint.court_x, shuttlePoint.court_y));
            }
        } else {
            setActiveShuttle(null);
            setActiveShuttlePos(null);
        }
    };

    const handleMatchIngested = (matchId: string) => {
        fetch("/api/v1/matches")
            .then(r => r.ok ? r.json() : [])
            .then(data => {
                let updatedMatches = data;
                if (!data || data.length === 0) {
                    const newMatch = {
                        match_id: matchId,
                        player_a_id: "00000000-0000-0000-0000-000000000001",
                        player_b_id: "00000000-0000-0000-0000-000000000002",
                        tournament: "Simulated Match Video",
                        match_date: new Date().toISOString().split("T")[0],
                        video_uri: "https://assets.mixkit.co/videos/preview/mixkit-badminton-player-hitting-shuttlecock-40019-large.mp4",
                        processing_status: "done",
                        fps: 30.0
                    };
                    updatedMatches = [newMatch, ...matches];
                }
                setMatches(updatedMatches);
                const found = updatedMatches.find((m: any) => m.match_id === matchId);
                if (found) {
                    setSelectedMatch(found);
                    setSelectedPlayer(found.player_a_id);
                }
            })
            .catch(() => {
                const newMatch = {
                    match_id: matchId,
                    player_a_id: "00000000-0000-0000-0000-000000000001",
                    player_b_id: "00000000-0000-0000-0000-000000000002",
                    tournament: "Simulated Match Video",
                    match_date: new Date().toISOString().split("T")[0],
                    video_uri: "https://assets.mixkit.co/videos/preview/mixkit-badminton-player-hitting-shuttlecock-40019-large.mp4",
                    processing_status: "done",
                    fps: 30.0
                };
                const updatedMatches = [newMatch, ...matches];
                setMatches(updatedMatches);
                setSelectedMatch(newMatch);
                setSelectedPlayer(newMatch.player_a_id);
            });
    };

    const getVideoUrl = (match: any) => {
        if (!match) return "https://assets.mixkit.co/videos/preview/mixkit-badminton-player-hitting-shuttlecock-40019-large.mp4";
        if (!match.video_uri || match.video_uri.startsWith("s3://") || match.video_uri.includes("dummy.mp4")) {
            return "https://assets.mixkit.co/videos/preview/mixkit-badminton-player-hitting-shuttlecock-40019-large.mp4";
        }
        return match.video_uri;
    };

    return (
        <div className="min-h-screen bg-black text-zinc-100 font-sans p-6 flex flex-col gap-6 selection:bg-indigo-500 selection:text-white">
            {/* Live Video Ingestion Processing Banner */}
            {liveStatus === "processing_cv" && (
                <div className="bg-indigo-950/30 border border-indigo-500/30 rounded-xl p-5 text-xs text-indigo-300 flex flex-col gap-3 shadow-lg animate-pulse">
                    <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                            <span className="w-2.5 h-2.5 rounded-full bg-indigo-500 animate-ping" />
                            <span><strong>Processing Match Video:</strong> Analyzing ball/shuttle trajectories and player coordinates in real time...</span>
                        </div>
                        <span className="font-bold text-indigo-400 font-mono text-sm">{liveProgress}%</span>
                    </div>
                    <div className="w-full bg-zinc-950 rounded-full h-2 overflow-hidden border border-zinc-900">
                        <div style={{ width: `${liveProgress}%` }} className="bg-gradient-to-r from-indigo-600 to-indigo-400 h-full rounded-full transition-all duration-300" />
                    </div>
                    {liveShuttle && (
                        <div className="text-[10px] text-zinc-400 font-mono flex gap-4">
                            <span>Speed: <strong className="text-zinc-200">{liveShuttle.speed} m/s</strong> ({Math.round(liveShuttle.speed * 3.6)} km/h)</span>
                            <span>Visible: <strong className="text-zinc-200">{liveShuttle.visible ? "Yes" : "No"}</strong></span>
                            {liveShuttle.court_x !== null && liveShuttle.court_x !== undefined && (
                                <span>Position: <strong className="text-zinc-200">({liveShuttle.court_x.toFixed(2)}, {liveShuttle.court_y.toFixed(2)})</strong></span>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Error Banner */}
            {errorMessage && (
                <div className="bg-rose-950/30 border border-rose-500/30 rounded-xl p-4 text-xs text-rose-300 flex items-center gap-2 shadow-lg">
                    <AlertCircle className="w-4 h-4 flex-shrink-0 text-rose-400" />
                    <span><strong>Connection Error:</strong> {errorMessage}</span>
                </div>
            )}

            {/* Header */}
            <header className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-zinc-950/80 border border-zinc-900 rounded-2xl p-6 backdrop-blur shadow-2xl">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-gradient-to-tr from-indigo-600 to-rose-600 flex items-center justify-center font-bold text-white shadow-lg">
                        A
                    </div>
                    <div>
                        <h1 className="text-2xl font-black bg-gradient-to-r from-white via-zinc-200 to-zinc-500 bg-clip-text text-transparent">
                            AuraSports Analytics
                        </h1>
                        <p className="text-xs text-zinc-400 font-medium">AuraSports Performance Analytics System v1.0</p>
                    </div>
                </div>
            </header>

            {/* Ingestion Panel Toggle */}
            <div className="flex justify-between items-center bg-zinc-950/60 border border-zinc-900 rounded-2xl p-6 shadow-2xl">
                <div>
                    <h2 className="text-base font-bold text-zinc-200">Process New Video Session</h2>
                    <p className="text-xs text-zinc-400">Upload a tennis ball / shuttle tracking video file, run TrackNet, and compile visual analysis.</p>
                </div>
                <button
                    onClick={() => setShowUploadForm(!showUploadForm)}
                    className="px-4 py-2 bg-indigo-650 hover:bg-indigo-500 text-white rounded-xl text-xs font-bold transition-all"
                >
                    {showUploadForm ? "Hide Upload Panel" : "Show Upload Panel"}
                </button>
            </div>

            {showUploadForm && (
                <MatchIngestionPanel
                    allPlayers={allPlayers}
                    onMatchIngested={handleMatchIngested}
                />
            )}

            {/* Main Visualizer Section */}
            <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
                {/* Left Area: Video Player & Log Table */}
                <div className="xl:col-span-2 flex flex-col gap-6">
                    {/* Interactive Video Player */}
                    <div className="bg-zinc-950 border border-zinc-900 rounded-2xl p-6 shadow-2xl flex flex-col gap-4">
                        <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 border-b border-zinc-900 pb-4">
                            <div>
                                <h3 className="text-base font-bold text-zinc-200">Interactive Tracked Video</h3>
                                <p className="text-xs text-zinc-400">Real-time video synchronizer with dynamic overlays</p>
                            </div>
                            <div className="flex items-center gap-2">
                                <button
                                    onClick={() => setShowSkeleton(!showSkeleton)}
                                    className={`px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase transition-all ${showSkeleton ? "bg-indigo-650 border border-indigo-500/30 text-white" : "bg-zinc-900 border border-zinc-850 text-zinc-400"}`}
                                >
                                    Skeletal Overlay
                                </button>
                                <button
                                    onClick={() => setShowSpeedTrail(!showSpeedTrail)}
                                    className={`px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase transition-all ${showSpeedTrail ? "bg-amber-600 border border-amber-500/30 text-white" : "bg-zinc-900 border border-zinc-850 text-zinc-400"}`}
                                >
                                    Speed Trail
                                </button>
                                <button
                                    onClick={() => setShowMiniMap(!showMiniMap)}
                                    className={`px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase transition-all ${showMiniMap ? "bg-emerald-650 border border-emerald-500/30 text-white" : "bg-zinc-900 border border-zinc-850 text-zinc-400"}`}
                                >
                                    PiP Mini-Map
                                </button>
                            </div>
                        </div>
                        <div 
                            onClick={handleContainerClick}
                            className="relative aspect-video bg-black rounded-xl overflow-hidden border border-zinc-800 group cursor-pointer"
                        >
                            <video
                                key={getVideoUrl(selectedMatch)}
                                ref={videoRef}
                                src={getVideoUrl(selectedMatch)}
                                controls
                                onTimeUpdate={handleTimeUpdate}
                                className="w-full h-full object-cover"
                            />
                            
                            {/* Dynamic HTML5 Canvas Overlay */}
                            <canvas
                                ref={canvasRef}
                                className="absolute top-0 left-0 w-full h-full pointer-events-none z-10"
                            />
                            
                            {/* Contextual HUD Overlay (Fades out after 2s) */}
                            {(() => {
                                const currentFrame = Math.round((playbackMs / 1000) * (selectedMatch?.fps || 30.0));
                                const recentShot = [...trajectories]
                                    .filter(t => t.frame_number <= currentFrame && t.frame_number >= currentFrame - 60 && t.event)
                                    .pop();
                                if (!recentShot) return null;
                                return (
                                    <div className="absolute bottom-4 left-4 right-4 bg-zinc-950/90 backdrop-blur border border-zinc-800/80 p-4 rounded-xl flex justify-between items-center text-xs font-mono shadow-2xl">
                                        <div className="flex flex-col">
                                            <span className="text-[10px] text-zinc-500 uppercase font-bold">Detected Stroke</span>
                                            <span className="text-sm text-indigo-400 font-bold uppercase">{recentShot.event}</span>
                                        </div>
                                        <div className="flex flex-col">
                                            <span className="text-[10px] text-zinc-500 uppercase font-bold">Smash Velocity</span>
                                            <span className="text-sm text-amber-500 font-bold">{Math.round(recentShot.speed || 0)} km/h</span>
                                        </div>
                                        {recentShot.landing_x_pred !== undefined && (
                                            <div className="flex flex-col">
                                                <span className="text-[10px] text-zinc-500 uppercase font-bold">Landing Pred</span>
                                                <span className="text-sm text-emerald-500 font-bold">({recentShot.landing_x_pred.toFixed(2)}, {recentShot.landing_y_pred?.toFixed(2)})</span>
                                            </div>
                                        )}
                                        {recentShot.time_to_landing !== undefined && (
                                            <div className="flex flex-col">
                                                <span className="text-[10px] text-zinc-500 uppercase font-bold">Time-to-Landing</span>
                                                <span className="text-sm text-rose-400 font-bold">{recentShot.time_to_landing.toFixed(2)}s</span>
                                            </div>
                                        )}
                                    </div>
                                );
                            })()}

                            <div className="absolute top-4 left-4 bg-zinc-950/80 backdrop-blur border border-zinc-800/80 px-3 py-1.5 rounded-lg pointer-events-none text-xs flex gap-4 font-mono">
                                <div>Time: <span className="text-indigo-400 font-bold">{Math.floor(playbackMs / 1000)}s</span></div>
                                <div>Frame: <span className="text-indigo-400 font-bold">{Math.round((playbackMs / 1000) * (selectedMatch?.fps || 30.0))}</span></div>
                            </div>
                        </div>
                    </div>

                    {/* Trajectory Coordinates Log Table */}
                    <div className="bg-zinc-950 border border-zinc-900 rounded-2xl p-6 shadow-2xl flex flex-col gap-4">
                        <div>
                            <h3 className="text-base font-bold text-zinc-200">Trajectory Coordinates Log</h3>
                            <p className="text-xs text-zinc-400">Detailed spatial-temporal records of the tracked trajectory</p>
                        </div>
                        <div className="max-h-72 overflow-y-auto border border-zinc-900 rounded-xl">
                            <table className="w-full text-left border-collapse text-xs">
                                <thead>
                                    <tr className="bg-zinc-900 border-b border-zinc-800 text-zinc-400 uppercase font-bold text-[10px]">
                                        <th className="p-3">Frame</th>
                                        <th className="p-3">Pixel (X, Y)</th>
                                        <th className="p-3">Court (X, Y)</th>
                                        <th className="p-3">Speed</th>
                                        <th className="p-3">Event</th>
                                    </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-900 font-mono text-zinc-300">
                                    {loading ? (
                                        <tr>
                                            <td colSpan={5} className="p-4 text-center text-zinc-500">Loading trajectories...</td>
                                        </tr>
                                    ) : trajectories && trajectories.length > 0 ? (
                                        trajectories.map((t) => {
                                            const currentFrame = Math.round((playbackMs / 1000) * (selectedMatch?.fps || 30.0));
                                            const isActive = currentFrame === t.frame_number || highlightedFrame === t.frame_number;
                                            return (
                                                <tr 
                                                    key={t.frame_number} 
                                                    id={`row-${t.frame_number}`}
                                                    onClick={() => {
                                                        handleSeek(t.frame_number * (1000 / (selectedMatch?.fps || 30.0)));
                                                        setHighlightedFrame(t.frame_number);
                                                    }}
                                                    className={`hover:bg-zinc-900/40 cursor-pointer transition-all ${isActive ? "bg-indigo-950/40 text-indigo-300 font-bold border-l-2 border-indigo-500" : ""}`}
                                                >
                                                    <td className="p-3 font-bold">{t.frame_number}</td>
                                                    <td className="p-3">
                                                        {t.x !== null && t.y !== null && t.x !== undefined && t.y !== undefined ? `(${Math.round(t.x)}, ${Math.round(t.y)})` : "-"}
                                                    </td>
                                                    <td className="p-3">
                                                        {t.court_x !== null && t.court_y !== null && t.court_x !== undefined && t.court_y !== undefined ? `(${t.court_x.toFixed(2)}, ${t.court_y.toFixed(2)})` : "-"}
                                                    </td>
                                                    <td className="p-3">
                                                        {t.speed !== null && t.speed > 0 ? `${t.speed.toFixed(1)} m/s (${Math.round(t.speed * 3.6)} km/h)` : "-"}
                                                    </td>
                                                    <td className="p-3 text-[10px]">
                                                        {t.event ? (
                                                            <span className="bg-indigo-950/65 text-indigo-400 border border-indigo-900 px-2 py-0.5 rounded uppercase font-bold">
                                                                {t.event}
                                                            </span>
                                                        ) : (
                                                            <span className="text-zinc-600">-</span>
                                                        )}
                                                    </td>
                                                </tr>
                                            );
                                        })
                                    ) : (
                                        <tr>
                                            <td colSpan={5} className="p-4 text-center text-zinc-500">No trajectory data available. Ingest a video to start tracking.</td>
                                        </tr>
                                    )}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>

                {/* Right Area: Court Heatmap */}
                <div>
                    <CourtHeatmap
                        grid={heatmapGrid}
                        types={heatmapTypes}
                        setTypes={setHeatmapTypes}
                        shotFilter={shotFilter}
                        setShotFilter={setShotFilter}
                        shots={shots}
                        activeShuttle={activeShuttle}
                    />
                </div>
            </div>
        </div>
    );
}
