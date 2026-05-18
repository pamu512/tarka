import { useMemo } from "react";
import Map, { Layer, Marker, NavigationControl, Source } from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";

import type { GeoCollisionModel } from "../../utils/geoCollisionExtract";
import { extractGeoCollisionModel } from "../../utils/geoCollisionExtract";

/** Carto Dark Matter (vector) — matches analyst dark UI (Prompt 160). */
const DARK_VECTOR_STYLE = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

type Props = {
  evaluatePayload: Record<string, unknown> | null | undefined;
  className?: string;
};

function collisionLineGeoJson(model: GeoCollisionModel) {
  return {
    type: "Feature" as const,
    properties: {},
    geometry: {
      type: "LineString" as const,
      coordinates: [
        [model.ip.lng, model.ip.lat],
        [model.shipping.lng, model.shipping.lat],
      ],
    },
  };
}

function MarkerBubble({
  tone,
  kindLabel,
  detail,
}: {
  tone: "ip" | "ship";
  kindLabel: string;
  detail: string;
}) {
  const ring = tone === "ip" ? "ring-sky-400/80 shadow-sky-500/30" : "ring-amber-400/80 shadow-amber-500/30";
  const bg = tone === "ip" ? "bg-sky-500/95" : "bg-amber-500/95";
  return (
    <div className={`flex flex-col items-center gap-0.5 translate-y-[-2px] ${ring}`} title={detail}>
      <div
        className={`rounded-full w-3 h-3 ${bg} border-2 border-white/95 shadow-lg`}
        aria-hidden
      />
      <div className="max-w-[10rem] rounded-md bg-surface-950/95 border border-surface-600 px-1.5 py-1 shadow-md">
        <div className="text-[9px] uppercase tracking-wide text-gray-500 text-center">{kindLabel}</div>
        <div className="text-[10px] font-medium text-gray-100 leading-snug text-center line-clamp-2">
          {detail}
        </div>
      </div>
    </div>
  );
}

function MapInner({ model }: { model: GeoCollisionModel }) {
  const lineGeo = useMemo(() => collisionLineGeoJson(model), [model]);

  const bounds = useMemo(() => {
    const lngs = [model.ip.lng, model.shipping.lng];
    const lats = [model.ip.lat, model.shipping.lat];
    return {
      minLng: Math.min(...lngs),
      maxLng: Math.max(...lngs),
      minLat: Math.min(...lats),
      maxLat: Math.max(...lats),
    };
  }, [model]);

  return (
    <Map
      mapStyle={DARK_VECTOR_STYLE}
      initialViewState={{
        bounds: [
          [bounds.minLng, bounds.minLat],
          [bounds.maxLng, bounds.maxLat],
        ],
        fitBoundsOptions: { padding: 72, maxZoom: 12 },
      }}
      style={{ width: "100%", height: 280 }}
      attributionControl={false}
      reuseMaps
      dragRotate={false}
      touchPitch={false}
    >
      <NavigationControl position="top-right" showCompass={false} />

      <Source id="geo-collision-line" type="geojson" data={lineGeo}>
        <Layer
          id="geo-collision-line-layer"
          type="line"
          paint={{
            "line-color": "#fbbf24",
            "line-width": 2,
            "line-opacity": 0.85,
            "line-dasharray": [1.8, 1.4],
          }}
        />
      </Source>

      <Marker longitude={model.ip.lng} latitude={model.ip.lat} anchor="bottom">
        <MarkerBubble tone="ip" kindLabel="Session IP" detail={model.ip.label} />
      </Marker>

      <Marker longitude={model.shipping.lng} latitude={model.shipping.lat} anchor="bottom">
        <MarkerBubble tone="ship" kindLabel="Ship-to" detail={model.shipping.label} />
      </Marker>
    </Map>
  );
}

/** Vector map: session IP vs ship-to — highlights geographic mismatch / collision (Prompt 160). */
export function GeographicCollisionMap({ evaluatePayload, className = "" }: Props) {
  const model = useMemo(() => extractGeoCollisionModel(evaluatePayload ?? undefined), [evaluatePayload]);

  return (
    <section
      className={`rounded-xl border border-surface-700 bg-surface-900/80 overflow-hidden ${className}`}
      aria-label="Geographic collision map"
    >
      <div className="px-4 py-3 border-b border-surface-800 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400">Geographic collision</h3>
          <p className="text-[11px] text-gray-500 mt-0.5 max-w-prose">
            Session IP location vs ship-to address — great-circle separation on a dark vector basemap.
          </p>
        </div>
        {model ? (
          <div className="text-right space-y-0.5">
            <div className="text-[11px] font-mono text-gray-300 tabular-nums">
              ≈ {model.straightLineKm < 100 ? model.straightLineKm.toFixed(1) : Math.round(model.straightLineKm)} km
              apart
            </div>
            <div className="text-[10px] text-gray-500">
              {model.precision === "coordinates" ? "Coordinate precision" : "Country centroids (fallback)"}
            </div>
          </div>
        ) : null}
      </div>

      {!model ? (
        <div className="px-4 py-6 text-sm text-gray-500">
          No map yet — structured{" "}
          <code className="text-[11px] text-gray-400">geo_collision.ip</code> /{" "}
          <code className="text-[11px] text-gray-400">shipping</code> on the audit envelope, or distinct{" "}
          <code className="text-[11px] text-gray-400">geo_country</code> vs{" "}
          <code className="text-[11px] text-gray-400">shipping_country</code>.
        </div>
      ) : (
        <div className="relative w-full min-h-[280px]">
          <MapInner model={model} />
          <p className="absolute bottom-2 left-3 text-[10px] text-gray-600 pointer-events-none">
            © OpenStreetMap © CARTO · vector style
          </p>
        </div>
      )}
    </section>
  );
}
