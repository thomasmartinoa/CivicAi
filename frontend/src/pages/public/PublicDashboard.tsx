import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import { getPublicDashboard, API_BASE_URL } from '../../services/api';
import type { DashboardStats } from '../../types';
import {
  PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer
} from 'recharts';
import type { PieLabelRenderProps } from 'recharts';

import { STATE_DISTRICT_MAP, STATE_COORDS } from '../../utils/locations';


// Fix leaflet icons
const iconRetinaUrl = new URL('leaflet/dist/images/marker-icon-2x.png', import.meta.url).href;
const iconUrl = new URL('leaflet/dist/images/marker-icon.png', import.meta.url).href;
const shadowUrl = new URL('leaflet/dist/images/marker-shadow.png', import.meta.url).href;

delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl,
  iconUrl,
  shadowUrl,
});

const createCustomIcon = (color: string) => {
  return L.divIcon({
    className: 'custom-div-icon',
    html: `<div style="background-color: ${color}; width: 14px; height: 14px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
};

const PIE_COLORS = ['#1e3a5f', '#2563eb', '#16a34a', '#eab308', '#ef4444', '#8b5cf6', '#6b7280'];
// The wire value comes from the backend's Category enum; the label is for people.
// The previous version held display names and uppercased them at call time, which
// turned "Public Spaces" into "PUBLIC SPACES" where the API wants "PUBLIC_SPACES" —
// so PUBLIC_SPACES, FIRE_HAZARD and STRAY_ANIMALS silently matched nothing.
const CATEGORIES: { value: string; label: string }[] = [
  { value: 'ROADS', label: 'Roads' },
  { value: 'ELECTRICITY', label: 'Electricity' },
  { value: 'WATER', label: 'Water' },
  { value: 'SANITATION', label: 'Sanitation' },
  { value: 'PUBLIC_SPACES', label: 'Public Spaces' },
  { value: 'EDUCATION', label: 'Education' },
  { value: 'HEALTH', label: 'Health' },
  { value: 'FLOODING', label: 'Flooding' },
  { value: 'FIRE_HAZARD', label: 'Fire Hazard' },
  { value: 'CONSTRUCTION', label: 'Construction' },
  { value: 'STRAY_ANIMALS', label: 'Stray Animals' },
  { value: 'SEWAGE', label: 'Sewage' },
];

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.map(c => [c.value, c.label])
);

// Map updater component
function MapUpdater({ markers, state, district }: { markers: any[], state: string, district: string }) {
  const map = useMap();
  useEffect(() => {
    map.invalidateSize();
    if (state && STATE_COORDS[state]) {
      const { lat, lng, zoom } = STATE_COORDS[state];
      map.setView([lat, lng], district ? zoom + 2 : zoom, { animate: true });
    } else if (markers.length > 0) {
      const bounds = L.latLngBounds(markers.map((m: any) => [m.lat, m.lng]));
      map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
    } else {
      map.setView([20.5937, 78.9629], 5, { animate: true });
    }
  }, [state, district]);
  return null;
}

// Still used on the recent-complaints cards, where risk_level IS published. It is
// no longer used on the map: a heatmap point is a grid cell and carries no risk.
const RISK_COLOR: Record<string, string> = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#eab308',
  low: '#22c55e',
};

/** A heatmap point is a coarsened grid cell, not a complaint: the public API sends
 *  lat/lng/weight/category and deliberately no status or risk level, because those
 *  belong to individual reports. Colouring by category is therefore the most the
 *  map can honestly say, and the marker grows with how many complaints fell in the
 *  cell. */
function getCategoryColor(category: string | null): string {
  if (!category) return '#6b7280';
  const index = CATEGORIES.findIndex(c => c.value === category);
  return index === -1 ? '#6b7280' : PIE_COLORS[index % PIE_COLORS.length];
}


export default function PublicDashboard() {
  const [selectedState, setSelectedState] = useState<string>('');
  const [selectedDistrict, setSelectedDistrict] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');

  const handleStateChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedState(e.target.value);
    setSelectedDistrict(''); // Reset district when state changes
  };

  const { data, isLoading, isError } = useQuery<DashboardStats>({
    queryKey: ['publicDashboard', selectedState, selectedDistrict, selectedCategory],
    queryFn: async () => {
      const res = await getPublicDashboard(undefined, selectedState || undefined, selectedDistrict || undefined, selectedCategory || undefined);
      return res.data;
    },
    placeholderData: (prev) => prev,
  });

  if (isError) {
    return (
      <div className="text-center py-20">
        <p className="text-red-600">Failed to load dashboard data.</p>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div>
      </div>
    );
  }


  const statusData = Object.entries(data?.by_status || {}).map(([name, value]) => ({ name, value }));
  const heatmapData = data?.heatmap_data || [];

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold text-gray-900">Public Dashboard</h1>
      </div>

      {/* Filter Bar */}
      <div className={`bg-white rounded-xl border border-gray-200 p-4 shadow-sm flex flex-col md:flex-row gap-4 transition-opacity ${isLoading ? 'opacity-60 pointer-events-none' : ''}`}>
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">State</label>
          <select
            value={selectedState}
            onChange={handleStateChange}
            className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
          >
            <option value="">All India</option>
            {Object.keys(STATE_DISTRICT_MAP).map(state => (
              <option key={state} value={state}>{state}</option>
            ))}
          </select>
        </div>

        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">District</label>
          <select
            value={selectedDistrict}
            onChange={(e) => setSelectedDistrict(e.target.value)}
            disabled={!selectedState}
            className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none disabled:bg-gray-100 disabled:text-gray-400"
          >
            <option value="">All Districts</option>
            {selectedState && STATE_DISTRICT_MAP[selectedState].map(district => (
              <option key={district} value={district}>{district}</option>
            ))}
          </select>
        </div>

        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">Category</label>
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="w-full border border-gray-300 rounded-lg px-4 py-2 focus:ring-2 focus:ring-blue-500 outline-none"
          >
            <option value="">All Categories</option>
            {CATEGORIES.map(category => (
              <option key={category.value} value={category.value}>{category.label}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Stats row & Status Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Status Pie Chart */}
        <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex flex-col justify-center items-center">
          <h2 className="text-lg font-semibold text-gray-800 mb-2 self-start">Status Distribution</h2>
          {statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={statusData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={(props: PieLabelRenderProps) => `${props.name ?? ''} (${(((props.percent as number) ?? 0) * 100).toFixed(0)}%)`}
                  outerRadius={80}
                  dataKey="value"
                >
                  {statusData.map((_, i) => (
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-400 text-center py-12">No data available for selected filters</p>
          )}
        </div>

        {/* KPI Cards (Right Column) */}
        <div className="flex flex-col gap-4 justify-between h-full">
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex-1 flex flex-col justify-center">
            <p className="text-sm text-gray-500 mb-1">Total Complaints</p>
            <p className="text-4xl font-bold text-blue-900">{data?.total_complaints || 0}</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex-1 flex flex-col justify-center">
            <p className="text-sm text-gray-500 mb-1">Resolved</p>
            <p className="text-4xl font-bold text-green-600">{data?.resolved_complaints || 0}</p>
          </div>
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm flex-1 flex flex-col justify-center">
            <p className="text-sm text-gray-500 mb-1">Resolution Rate</p>
            <p className="text-4xl font-bold text-purple-600">
              {data?.resolution_rate == null ? 'No data' : `${(data.resolution_rate * 100).toFixed(1)}%`}
            </p>
          </div>
        </div>
      </div>

      {/* Map Section */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm relative z-0">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-gray-800">Infrastructure Issues Map</h2>
          <div className="flex gap-4 text-xs">
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-red-500 inline-block"></span> Critical</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-orange-400 inline-block"></span> High</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-yellow-400 inline-block"></span> Medium</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-green-500 inline-block"></span> Resolved / Low</span>
          </div>
        </div>
        <div className="h-[500px] w-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200">
          <MapContainer
            center={[20.5937, 78.9629]}
            zoom={5}
            scrollWheelZoom={false}
            style={{ height: '100%', width: '100%' }}
            className="z-0"
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />

            {heatmapData.map((marker: any, i: number) => (
              <Marker
                key={i}
                position={[marker.lat, marker.lng]}
                icon={createCustomIcon(getCategoryColor(marker.category))}
              >
                <Popup>
                  <div className="text-sm font-semibold mb-1">{marker.category || 'Unknown'}</div>
                  <div className="text-xs text-gray-600">
                    {marker.weight === 1 ? '1 complaint' : `${marker.weight} complaints`} in this area
                  </div>
                  <div className="text-xs text-gray-400 mt-1">Location shown to the nearest ~100 m</div>
                </Popup>
              </Marker>
            ))}

            <MapUpdater markers={heatmapData} state={selectedState} district={selectedDistrict} />
          </MapContainer>
        </div>
      </div>

      {/* Complaints List */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm mt-8">
        <h2 className="text-xl font-semibold text-gray-800 mb-6">
          Latest Issues {selectedCategory ? `in ${CATEGORY_LABELS[selectedCategory] ?? selectedCategory}` : ''}
        </h2>
        {data?.recent_complaints && data.recent_complaints.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {data.recent_complaints.map((c: any) => (
              <div key={c.id} className="border border-gray-100 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition">
                {c.media_url ? (
                  <img src={`${API_BASE_URL}/${c.media_url}`} alt={c.category} className="w-full h-48 object-cover" />
                ) : (
                  <div className="w-full h-48 bg-gray-50 flex flex-col items-center justify-center text-gray-400">
                    <svg className="w-8 h-8 mb-2 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path></svg>
                    <span>No Image Available</span>
                  </div>
                )}
                <div className="p-4">
                  <div className="flex justify-between items-start mb-3">
                    <span className="text-xs font-semibold px-2 py-1 bg-blue-100 text-blue-800 rounded-lg">{c.category || 'General'}</span>
                    <span className={`text-xs font-semibold px-2 py-1 rounded-lg ${c.status === 'resolved' ? 'bg-green-100 text-green-800' : 'bg-yellow-100 text-yellow-800'}`}>
                      {c.status}
                    </span>
                  </div>
                  {c.risk_level && (
                    <p className="text-sm font-medium mb-3 capitalize"
                       style={{ color: RISK_COLOR[c.risk_level] ?? '#374151' }}>
                      {c.risk_level} risk
                    </p>
                  )}
                  <div className="text-xs text-gray-500 space-y-1">
                    {/* District and state, never the street: the public API withholds
                        the address, because a place plus a date is often a household. */}
                    <p className="flex items-start gap-1">📍 <span>
                      {[c.district, c.state].filter(Boolean).join(', ') || 'Location not specified'}
                    </span></p>
                    <p className="flex items-center gap-1">📅 <span>{new Date(c.created_at).toLocaleDateString()}</span></p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-center text-gray-500 py-8">No issues found matching the selected filters.</p>
        )}
      </div>

      {/* Geotagged count */}
      {data.heatmap_data && data.heatmap_data.length > 0 && (
        <div className="text-center text-sm text-gray-400">
          Showing {data.heatmap_data.length} geotagged complaint{data.heatmap_data.length !== 1 ? 's' : ''} on map
        </div>
      )}
    </div>
  );
}
