import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getPublicDashboard } from '../../services/api';
import type { DashboardStats } from '../../types';
import {
  PieChart, Pie, Cell, Legend, Tooltip, ResponsiveContainer
} from 'recharts';
import type { PieLabelRenderProps } from 'recharts';
import { MapContainer, TileLayer, Marker, Popup, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { STATE_DISTRICT_MAP } from '../../utils/locations';
import L from 'leaflet';

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
const CATEGORIES = ["Roads", "Electricity", "Water", "Sanitation", "Public Spaces", "Education", "Health", "Flooding", "Fire Hazard", "Construction", "Stray Animals", "Sewage"];

// Map updater component
function MapUpdater({ markers, state, district }: { markers: any[], state: string, district: string }) {
  const map = useMap();
  useEffect(() => {
    const place = district ? `${district}, ${state}, India` : (state ? `${state}, India` : '');

    if (place) {
      // Use Nominatim to get bounding box for the state/district
      fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(place)}`)
        .then(res => res.json())
        .then(data => {
          if (data && data.length > 0) {
            const bbox = data[0].boundingbox; // [latMin, latMax, lonMin, lonMax]
            if (bbox) {
              const bounds = L.latLngBounds(
                [parseFloat(bbox[0]), parseFloat(bbox[2])],
                [parseFloat(bbox[1]), parseFloat(bbox[3])]
              );
              map.fitBounds(bounds, { padding: [20, 20] });
            } else {
              map.setView([parseFloat(data[0].lat), parseFloat(data[0].lon)], district ? 10 : 6);
            }
          } else if (markers.length > 0) {
            const bounds = L.latLngBounds(markers.map(m => [m.lat, m.lng]));
            map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
          }
        })
        .catch(err => {
          console.error("Geocoding failed", err);
          if (markers.length > 0) {
            const bounds = L.latLngBounds(markers.map(m => [m.lat, m.lng]));
            map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
          }
        });
    } else {
      if (markers.length > 0) {
        const bounds = L.latLngBounds(markers.map(m => [m.lat, m.lng]));
        map.fitBounds(bounds, { padding: [50, 50], maxZoom: 12 });
      } else {
        map.setView([20.5937, 78.9629], 5); // Default India view
      }
    }
  }, [markers, state, district, map]);
  return null;
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
      const res = await getPublicDashboard(undefined, selectedState || undefined, selectedDistrict || undefined, selectedCategory ? selectedCategory.toUpperCase() : undefined);
      return res.data;
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-900"></div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="text-center py-20">
        <p className="text-red-600">Failed to load dashboard data.</p>
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
      <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm flex flex-col md:flex-row gap-4">
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
            {CATEGORIES.map(cat => (
              <option key={cat} value={cat}>{cat}</option>
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
              {((data?.resolution_rate || 0) * 100).toFixed(1)}%
            </p>
          </div>
        </div>
      </div>

      {/* Map Section */}
      <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm relative z-0">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-gray-800">Infrastructure Issues Map</h2>
          <div className="flex gap-4 text-xs">
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-red-500 inline-block"></span> High Risk</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-yellow-400 inline-block"></span> Moderate</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-green-500 inline-block"></span> Resolved</span>
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
                icon={createCustomIcon(marker.color)}
              >
                <Popup>
                  <div className="text-sm font-semibold mb-1">{marker.category || 'Unknown'}</div>
                  <div className="text-xs text-gray-600 capitalize">Status: {marker.status}</div>
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
          Latest Issues {selectedCategory ? `in ${selectedCategory}` : ''}
        </h2>
        {data?.recent_complaints && data.recent_complaints.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {data.recent_complaints.map((c: any) => (
              <div key={c.id} className="border border-gray-100 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition">
                {c.media_url ? (
                  <img src={`http://localhost:8000/${c.media_url}`} alt={c.category} className="w-full h-48 object-cover" />
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
                  <p className="text-sm text-gray-800 font-medium mb-3 line-clamp-2">{c.description}</p>
                  <div className="text-xs text-gray-500 space-y-1">
                    <p className="flex items-start gap-1">📍 <span>{c.address || 'Location not specified'}</span></p>
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
    </div>
  );
}
