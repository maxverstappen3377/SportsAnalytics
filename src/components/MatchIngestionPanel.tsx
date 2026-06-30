"use client";
import React, { useState } from "react";
import { AlertCircle, Sparkles, Upload, Link } from "lucide-react";

interface Player {
    player_id: string;
    name: string;
}

interface MatchIngestionPanelProps {
    allPlayers: Player[];
    onMatchIngested: (matchId: string) => void;
}

type IngestMode = "upload" | "url";

export default function MatchIngestionPanel({ allPlayers, onMatchIngested }: MatchIngestionPanelProps) {
    const [ingestMode, setIngestMode] = useState<IngestMode>("upload");
    const [videoFile, setVideoFile] = useState<File | null>(null);
    const [videoUrl, setVideoUrl] = useState<string>("");
    const [validationError, setValidationError] = useState<string | null>(null);
    const [uploadingVideo, setUploadingVideo] = useState(false);
    const [ingestStatus, setIngestStatus] = useState<string>("");
    const [ingestProgress, setIngestProgress] = useState(0);
    const [ingestError, setIngestError] = useState<string | null>(null);

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setValidationError(null);
        setVideoFile(null);
        if (e.target.files && e.target.files.length > 0) {
            const file = e.target.files[0];
            const name = file.name.toLowerCase();
            const allowedExtensions = [".mp4", ".mov", ".avi", ".mkv"];
            const hasValidExtension = allowedExtensions.some(ext => name.endsWith(ext));
            if (!hasValidExtension) {
                setValidationError("Invalid file format. Only .mp4, .mov, .avi, and .mkv files are allowed.");
                return;
            }
            if (file.size > 100 * 1024 * 1024) {
                setValidationError("File size exceeds 100MB limit.");
                return;
            }
            setVideoFile(file);
        }
    };

    const pollIngestionStatus = (matchId: string) => {
        const intervalId = setInterval(async () => {
            try {
                const res = await fetch(`/api/v1/matches/${matchId}/status`);
                if (!res.ok) throw new Error("Status check failed");
                const data = await res.json();
                
                setIngestStatus(data.status);
                setIngestProgress(data.progress);

                if (data.status === "done") {
                    clearInterval(intervalId);
                    onMatchIngested(matchId);
                } else if (data.status === "failed") {
                    clearInterval(intervalId);
                    setIngestError(data.error || "CV pipeline failed.");
                }
            } catch (err: any) {
                clearInterval(intervalId);
                setIngestStatus("failed");
                setIngestError(err.message || "Status polling failed");
            }
        }, 2050);
    };

    const handleCreateMatchAndIngest = async (e: React.FormEvent) => {
        e.preventDefault();
        setValidationError(null);
        setIngestError(null);

        if (ingestMode === "upload" && !videoFile) {
            setValidationError("Please select a video file to ingest.");
            return;
        }

        if (ingestMode === "url" && !videoUrl.trim()) {
            setValidationError("Please paste a valid video URL.");
            return;
        }

        setUploadingVideo(true);
        setIngestStatus("creating_metadata");
        setIngestProgress(5);

        try {
            // Find default player IDs from list, or use seeded defaults
            const playerAId = allPlayers.length > 0 ? allPlayers[0].player_id : "00000000-0000-0000-0000-000000000001";
            const playerBId = allPlayers.length > 1 ? allPlayers[1].player_id : "00000000-0000-0000-0000-000000000002";

            const createRes = await fetch("/api/v1/matches", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    player_a_id: playerAId,
                    player_b_id: playerBId,
                    tournament: "TrackNet Video Session",
                    match_date: new Date().toISOString().split("T")[0],
                    source_type: "broadcast",
                    video_url: ingestMode === "url" ? videoUrl.trim() : null
                })
            });

            if (!createRes.ok) {
                const errData = await createRes.json();
                throw new Error(errData.detail || "Failed to create match metadata");
            }

            const newMatchObj = await createRes.json();
            const matchId = newMatchObj.match_id;

            if (ingestMode === "upload") {
                const uploadUrl = newMatchObj.court_calibration?.upload_url;
                if (!uploadUrl) {
                    throw new Error("No upload URL returned by the backend");
                }

                setIngestStatus("uploading_video_file");
                setIngestProgress(20);

                const formData = new FormData();
                formData.append("file", videoFile!);

                const xhr = new XMLHttpRequest();
                await new Promise<void>((resolve, reject) => {
                    xhr.open("PUT", uploadUrl, true);
                    
                    xhr.upload.onprogress = (event) => {
                        if (event.lengthComputable) {
                            const percent = Math.round((event.loaded / event.total) * 50) + 20;
                            setIngestProgress(percent);
                        }
                    };
                    
                    xhr.onload = () => {
                        if (xhr.status === 200 || xhr.status === 201 || xhr.status === 204) {
                            resolve();
                        } else {
                            reject(new Error(`Upload failed with status ${xhr.status}`));
                        }
                    };
                    
                    xhr.onerror = () => reject(new Error("Network error during video upload"));
                    xhr.send(formData);
                });
            } else {
                setIngestStatus("linking_url");
                setIngestProgress(50);
                await new Promise(r => setTimeout(r, 300));
            }

            setIngestStatus("finalizing_upload");
            setIngestProgress(75);
            await new Promise(r => setTimeout(r, 400));

            setIngestStatus("queued");
            setIngestProgress(80);
            
            const confirmRes = await fetch(`/api/v1/matches/${matchId}/video/confirm`, {
                method: "POST"
            });

            if (!confirmRes.ok) {
                const errData = await confirmRes.json();
                throw new Error(errData.detail || "Failed to initiate CV processing");
            }

            setUploadingVideo(false);
            pollIngestionStatus(matchId);

        } catch (err: any) {
            setUploadingVideo(false);
            setIngestStatus("failed");
            setIngestError(err.message || "An error occurred");
        }
    };

    return (
        <div className="bg-zinc-950/60 border border-zinc-900 rounded-2xl p-6 shadow-2xl flex flex-col gap-6">
            {validationError && (
                <div className="bg-rose-950/20 border border-rose-900/50 rounded-xl p-4 text-xs text-rose-300 flex items-center gap-2">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>{validationError}</span>
                </div>
            )}

            {/* Mode selection tabs */}
            <div className="flex border-b border-zinc-900 pb-1">
                <button
                    onClick={() => { setIngestMode("upload"); setValidationError(null); }}
                    className={`flex items-center gap-2 pb-2.5 px-4 text-xs font-bold uppercase transition-all border-b-2 ${ingestMode === "upload" ? "border-indigo-500 text-white" : "border-transparent text-zinc-400 hover:text-zinc-200"}`}
                >
                    <Upload className="w-3.5 h-3.5" />
                    Upload File
                </button>
                <button
                    onClick={() => { setIngestMode("url"); setValidationError(null); }}
                    className={`flex items-center gap-2 pb-2.5 px-4 text-xs font-bold uppercase transition-all border-b-2 ${ingestMode === "url" ? "border-indigo-500 text-white" : "border-transparent text-zinc-400 hover:text-zinc-200"}`}
                >
                    <Link className="w-3.5 h-3.5" />
                    Paste Video URL
                </button>
            </div>

            <form onSubmit={handleCreateMatchAndIngest} className="flex flex-col gap-4">
                {ingestMode === "upload" ? (
                    <div key="file-input-wrapper" className="flex flex-col gap-2">
                        <label className="text-[10px] font-bold text-zinc-400 uppercase">Select Video File (.mp4, .mov, .avi, .mkv)</label>
                        <input
                            key="file-input"
                            type="file"
                            accept=".mp4,.mov,.avi,.mkv"
                            onChange={handleFileChange}
                            className="bg-zinc-900 border border-zinc-850 rounded-xl px-4 py-3.5 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500 file:mr-4 file:py-1 file:px-3 file:rounded-md file:border-0 file:text-[10px] file:font-semibold file:bg-zinc-800 file:text-zinc-200 hover:file:bg-zinc-700"
                        />
                    </div>
                ) : (
                    <div key="url-input-wrapper" className="flex flex-col gap-2">
                        <label className="text-[10px] font-bold text-zinc-400 uppercase">Video Stream URL (MP4 / Direct Link)</label>
                        <input
                            key="url-input"
                            type="text"
                            placeholder="https://example.com/badminton_rally.mp4"
                            value={videoUrl}
                            onChange={(e) => { setValidationError(null); setVideoUrl(e.target.value); }}
                            className="bg-zinc-900 border border-zinc-850 rounded-xl px-4 py-3.5 text-xs text-zinc-300 focus:outline-none focus:border-indigo-500"
                        />
                    </div>
                )}

                <button
                    type="submit"
                    disabled={uploadingVideo || (ingestStatus !== "" && ingestStatus !== "done" && ingestStatus !== "failed")}
                    className="w-full py-3 bg-indigo-650 hover:bg-indigo-600 disabled:bg-zinc-800 disabled:text-zinc-600 text-white rounded-xl text-xs font-bold transition-all shadow-lg uppercase"
                >
                    {uploadingVideo ? "Uploading / processing..." : "Start Ingestion & Track"}
                </button>
            </form>

            {/* Status Feedback */}
            {ingestStatus && (
                <div className="border-t border-zinc-900 pt-4 flex flex-col gap-3">
                    <div className="flex justify-between items-center text-xs">
                        <span className="text-zinc-400 font-bold uppercase">
                            Processing Status: <span className="text-indigo-400 font-mono">{ingestStatus}</span>
                        </span>
                        <span className="text-zinc-400 font-mono font-bold">{ingestProgress}%</span>
                    </div>
                    <div className="w-full bg-zinc-900 rounded-full h-2.5 border border-zinc-850 overflow-hidden">
                        <div
                            className="bg-indigo-600 h-2.5 transition-all duration-500"
                            style={{ width: `${ingestProgress}%` }}
                        />
                    </div>
                    {ingestError && (
                        <div className="bg-rose-950/20 border border-rose-900/50 rounded-xl p-4 text-xs text-rose-300 flex items-center gap-2">
                            <AlertCircle className="w-4 h-4 flex-shrink-0" />
                            <span>{ingestError}</span>
                        </div>
                    )}
                    {ingestStatus === "done" && (
                        <div className="bg-emerald-950/20 border border-emerald-900/50 rounded-xl p-4 text-xs text-emerald-300 flex items-center gap-2">
                            <Sparkles className="w-4 h-4 flex-shrink-0 text-emerald-400" />
                            <span>Ingestion completed successfully! Tracked video is ready for analysis.</span>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
