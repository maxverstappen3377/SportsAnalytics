"use client";

import React from "react";

interface HeatmapProps {
    grid: number[][];
    types: string[];
    setTypes: (t: string[]) => void;
    shotFilter: string;
    setShotFilter: (s: string) => void;
    shots: any[];
    activeShuttle?: any;
    activePlayerA?: any;
    activePlayerB?: any;
}

export default function CourtHeatmap({ grid, types, setTypes, shotFilter, setShotFilter, shots = [], activeShuttle, activePlayerA, activePlayerB }: HeatmapProps) {
    // Shot types
    const shotTypes = [
        "All Shots", "short serve", "long/flick serve",
        "net shot", "push/net kill", "defensive clear",
        "attacking clear", "lift", "drop shot", "drive", "smash"
    ];

    // Find max value in grid for density normalization
    const maxVal = grid ? Math.max(...grid.map(row => Math.max(...row, 0)), 1) : 1;

    const toggleType = (t: string) => {
        if (types.includes(t)) {
            setTypes(types.filter(x => x !== t));
        } else {
            setTypes([...types, t]);
        }
    };

    // Filter shots for discrete landing dots
    const filteredShots = shots.filter(shot => {
        if (shotFilter !== "All Shots" && shot.shot_type !== shotFilter) {
            return false;
        }
        return shot.landing_x !== null && shot.landing_y !== null && shot.landing_x !== undefined && shot.landing_y !== undefined;
    });

    return (
        <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 flex flex-col gap-6">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                    <h2 className="text-xl font-bold text-zinc-100">Court Heatmap</h2>
                    <p className="text-sm text-zinc-400">Spatial distribution of shots and landing positions</p>
                </div>
                
                <div className="flex items-center bg-zinc-800 rounded-lg p-1">
                    <button
                        onClick={() => toggleType("hit")}
                        className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                            types.includes("hit") ? "bg-indigo-600 text-white shadow" : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        Hitting Position
                    </button>
                    <button
                        onClick={() => toggleType("landing")}
                        className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                            types.includes("landing") ? "bg-indigo-600 text-white shadow" : "text-zinc-400 hover:text-zinc-200"
                        }`}
                    >
                        Landing Position
                    </button>
                </div>
            </div>

            <div className="flex flex-wrap gap-2">
                {shotTypes.map(s => (
                    <button
                        key={s}
                        onClick={() => setShotFilter(s)}
                        className={`px-3 py-1 rounded-full text-xs font-medium border transition-all ${
                            shotFilter === s
                                ? "bg-indigo-500/20 border-indigo-500 text-indigo-300"
                                : "bg-zinc-800/50 border-zinc-700 text-zinc-400 hover:text-zinc-200 hover:border-zinc-600"
                        }`}
                    >
                        {s}
                    </button>
                ))}
            </div>

            {/* SVG Court with Heatmap Grid Overlay */}
            <div className="relative w-full max-w-lg mx-auto aspect-[6.1/13.4] bg-emerald-950/40 rounded-lg border-2 border-zinc-700 overflow-hidden shadow-inner">
                {/* 2D Grid Cells Overlay */}
                <div className="absolute inset-0 grid grid-rows-20 grid-cols-10 pointer-events-none opacity-85">
                    {types.includes("hit") && grid && grid.map((row, rIdx) => 
                        row.map((val, cIdx) => {
                            if (val === 0) return <div key={`${rIdx}-${cIdx}`} />;
                            const pct = val / maxVal;
                            return (
                                <div
                                    key={`${rIdx}-${cIdx}`}
                                    style={{
                                        backgroundColor: `rgba(239, 68, 68, ${pct * 0.7})`,
                                        boxShadow: `0 0 12px rgba(239, 68, 68, ${pct * 0.5})`
                                    }}
                                    className="w-full h-full transition-all duration-500"
                                />
                            );
                        })
                    )}
                </div>

                {/* SVG Court Boundary Lines */}
                <svg viewBox="0 0 610 1340" className="absolute inset-0 w-full h-full stroke-zinc-400/30 fill-none">
                    {/* Outer court boundary */}
                    <rect x="0" y="0" width="610" height="1340" className="stroke-zinc-300/80 stroke-[4]" />

                    {/* Left/Right singles side lines */}
                    <line x1="46" y1="0" x2="46" y2="1340" className="stroke-[3]" />
                    <line x1="564" y1="0" x2="564" y2="1340" className="stroke-[3]" />

                    {/* Short service lines */}
                    <line x1="0" y1="468" x2="610" y2="468" className="stroke-[3]" />
                    <line x1="0" y1="872" x2="610" y2="872" className="stroke-[3]" />

                    {/* Long service lines (doubles) */}
                    <line x1="0" y1="76" x2="610" y2="76" className="stroke-[3]" />
                    <line x1="0" y1="1264" x2="610" y2="1264" className="stroke-[3]" />

                    {/* Center line */}
                    <line x1="305" y1="0" x2="305" y2="468" className="stroke-[3]" />
                    <line x1="305" y1="872" x2="305" y2="1340" className="stroke-[3]" />

                    {/* Net Line (middle) */}
                    <line x1="0" y1="670" x2="610" y2="670" className="stroke-red-500/50 stroke-[6]" />

                    {/* Landing vector dots overlay */}
                    {types.includes("landing") && filteredShots.map((shot) => {
                        const x = (shot.landing_x ?? 0) * 610;
                        const y = (shot.landing_y ?? 0) * 1340;
                        return (
                            <circle
                                key={shot.shot_id}
                                cx={x}
                                cy={y}
                                r={8}
                                className="fill-cyan-400 stroke-cyan-200 stroke-[2] cursor-pointer"
                                style={{ filter: "drop-shadow(0 0 6px rgba(34, 211, 238, 0.8))" }}
                            />
                        );
                    })}
                    {/* Active Player A position */}
                    {activePlayerA && activePlayerA.court_x !== undefined && activePlayerA.court_x !== null && (
                        <>
                            <circle
                                cx={activePlayerA.court_x * 610}
                                cy={activePlayerA.court_y * 1340}
                                r={16}
                                className="fill-emerald-500/25 animate-ping"
                            />
                            <circle
                                cx={activePlayerA.court_x * 610}
                                cy={activePlayerA.court_y * 1340}
                                r={10}
                                className="fill-emerald-500 stroke-emerald-200 stroke-2"
                                style={{ filter: "drop-shadow(0 0 6px rgba(16, 185, 129, 0.8))" }}
                            />
                        </>
                    )}

                    {/* Active Player B position */}
                    {activePlayerB && activePlayerB.court_x !== undefined && activePlayerB.court_x !== null && (
                        <>
                            <circle
                                cx={activePlayerB.court_x * 610}
                                cy={activePlayerB.court_y * 1340}
                                r={16}
                                className="fill-cyan-500/25 animate-ping"
                            />
                            <circle
                                cx={activePlayerB.court_x * 610}
                                cy={activePlayerB.court_y * 1340}
                                r={10}
                                className="fill-cyan-500 stroke-cyan-200 stroke-2"
                                style={{ filter: "drop-shadow(0 0 6px rgba(34, 211, 238, 0.8))" }}
                            />
                        </>
                    )}

                    {/* Active Shuttlecock position */}
                    {activeShuttle && activeShuttle.court_x !== undefined && activeShuttle.court_x !== null && (
                        <>
                            <circle
                                cx={activeShuttle.court_x * 610}
                                cy={activeShuttle.court_y * 1340}
                                r={12}
                                className="fill-yellow-400/30 animate-ping"
                            />
                            <circle
                                cx={activeShuttle.court_x * 610}
                                cy={activeShuttle.court_y * 1340}
                                r={6}
                                className="fill-yellow-400 stroke-white stroke-2"
                                style={{ filter: "drop-shadow(0 0 8px rgba(253, 224, 71, 1))" }}
                            />
                        </>
                    )}
                </svg>

                {/* Net indicator label */}
                <div className="absolute top-[50%] left-1/2 transform -translate-x-1/2 -translate-y-1/2 bg-red-600/90 text-white text-[10px] font-bold py-0.5 px-3 rounded-full shadow tracking-wider uppercase">
                    Net
                </div>
            </div>
        </div>
    );
}
