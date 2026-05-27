import { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  Upload, RefreshCw, CheckCircle, AlertTriangle, XCircle, Lock,
  ShieldAlert, ShieldCheck, Database, ClipboardList, Filter, Search,
  Check, X, ChevronRight, ChevronLeft, BarChart3
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

export default function App() {
  // State
  const [records, setRecords] = useState([]);
  const [dataSources, setDataSources] = useState([]);
  const [audits, setAudits] = useState([]);
  const [metrics, setMetrics] = useState({
    total_co2e: 0,
    scope_1: 0,
    scope_2: 0,
    scope_3: 0,
    counts: { total: 0, pending: 0, approved: 0, rejected: 0, failed: 0, suspicious: 0 },
    monthly_emissions: [],
    issues_summary: []
  });

  // Selected details
  const [selectedRecord, setSelectedRecord] = useState(null);
  const [selectedUploadSource, setSelectedUploadSource] = useState('');
  const [selectedFile, setSelectedFile] = useState(null);
  const [syncingSourceId, setSyncingSourceId] = useState(null);
  const [reviewReason, setReviewReason] = useState('');
  const [bulkSelectIds, setBulkSelectIds] = useState([]);
  const [uploadStatus, setUploadStatus] = useState({ state: 'idle', msg: '' });
  const [currentPage, setCurrentPage] = useState(1);

  // Filters
  const [filterValStatus, setFilterValStatus] = useState('');
  const [filterRevStatus, setFilterRevStatus] = useState('');
  const [filterSourceType, setFilterSourceType] = useState('');
  const [filterScope, setFilterScope] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  // Reset page to 1 when filters or search change
  useEffect(() => {
    setCurrentPage(1);
  }, [filterValStatus, filterRevStatus, filterSourceType, filterScope, searchTerm]);

  // Fetch records with filters
  const fetchRecords = useCallback(async () => {
    try {
      let recordsUrl = `${API_BASE}/records/?`;
      if (filterValStatus) recordsUrl += `validation_status=${filterValStatus}&`;
      if (filterRevStatus) recordsUrl += `review_status=${filterRevStatus}&`;
      if (filterSourceType) recordsUrl += `source_type=${filterSourceType}&`;
      if (filterScope) recordsUrl += `scope_category=${filterScope}&`;
      if (searchTerm) recordsUrl += `search=${searchTerm}&`;

      const resRecords = await axios.get(recordsUrl);
      setRecords(resRecords.data);
    } catch (err) {
      console.error("Error fetching records:", err);
    }
  }, [filterValStatus, filterRevStatus, filterSourceType, filterScope, searchTerm]);

  // Fetch static/metadata once
  const loadMetadata = useCallback(async () => {
    try {
      const resMetrics = await axios.get(`${API_BASE}/metrics/`);
      setMetrics(resMetrics.data);

      const resSources = await axios.get(`${API_BASE}/data-sources/`);
      setDataSources(resSources.data);
      if (resSources.data.length > 0) {
        setSelectedUploadSource(prev => prev || resSources.data[0].id);
      }

      const resAudits = await axios.get(`${API_BASE}/audits/`);
      setAudits(resAudits.data);
    } catch (err) {
      console.error("Error loading metadata:", err);
    }
  }, []);

  // Unified loader for manual triggers (e.g. after upload, approval)
  const loadData = useCallback(() => {
    loadMetadata();
    fetchRecords();
  }, [loadMetadata, fetchRecords]);

  useEffect(() => {
    fetchRecords();
  }, [fetchRecords]);

  useEffect(() => {
    loadMetadata();
  }, [loadMetadata]);

  // Pagination Calculations
  const RECORDS_PER_PAGE = 10;
  const totalPages = Math.ceil(records.length / RECORDS_PER_PAGE) || 1;
  const indexOfLastRecord = currentPage * RECORDS_PER_PAGE;
  const indexOfFirstRecord = indexOfLastRecord - RECORDS_PER_PAGE;
  const currentRecords = records.slice(indexOfFirstRecord, indexOfLastRecord);

  // Handle File Upload
  const handleFileUpload = async (e) => {
    e.preventDefault();
    if (!selectedFile || !selectedUploadSource) {
      setUploadStatus({ state: 'error', msg: 'Please select a file and data source.' });
      return;
    }

    setUploadStatus({ state: 'loading', msg: 'Uploading and parsing CSV...' });
    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('data_source_id', selectedUploadSource);

    try {
      await axios.post(`${API_BASE}/uploads/upload-file/`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      setUploadStatus({ state: 'success', msg: 'CSV ingested and normalized successfully!' });
      setSelectedFile(null);
      // Reset input element
      document.getElementById('csv-file-input').value = '';
      loadData();
    } catch (err) {
      console.error(err);
      const errMsg = err.response?.data?.error || 'Ingestion failed. Check file formatting.';
      setUploadStatus({ state: 'error', msg: errMsg });
    }
  };

  // Handle API Sync
  const handleApiSync = async (sourceId) => {
    setSyncingSourceId(sourceId);
    try {
      await axios.post(`${API_BASE}/uploads/sync-api/`, { data_source_id: sourceId });
      loadData();
    } catch (err) {
      console.error("API Sync error:", err);
      alert("API Sync failed: " + (err.response?.data?.error || err.message));
    } finally {
      setSyncingSourceId(null);
    }
  };

  // Handle Approve
  const handleApprove = async (recordId) => {
    if (!reviewReason.trim()) {
      alert("Please provide a justification override reason for approval.");
      return;
    }
    try {
      const res = await axios.post(`${API_BASE}/records/${recordId}/approve/`, { reason: reviewReason });
      setSelectedRecord(res.data);
      setReviewReason('');
      loadData();
    } catch (err) {
      alert("Approval failed: " + (err.response?.data?.error || err.message));
    }
  };

  // Handle Reject
  const handleReject = async (recordId) => {
    if (!reviewReason.trim()) {
      alert("Please provide a justification reason for rejection.");
      return;
    }
    try {
      const res = await axios.post(`${API_BASE}/records/${recordId}/reject/`, { reason: reviewReason });
      setSelectedRecord(res.data);
      setReviewReason('');
      loadData();
    } catch (err) {
      alert("Rejection failed: " + (err.response?.data?.error || err.message));
    }
  };

  // Handle Bulk Approve
  const handleBulkApprove = async () => {
    if (bulkSelectIds.length === 0) return;
    const reason = prompt("Please enter a justification reason for bulk approval:");
    if (reason === null) return; // User cancelled
    if (!reason.trim()) {
      alert("A justification reason is required for bulk approval.");
      return;
    }
    try {
      const res = await axios.post(`${API_BASE}/records/bulk-approve/`, { record_ids: bulkSelectIds, reason: reason });
      alert(`Bulk approved ${res.data.approved_count} records. (Failed records with errors were skipped)`);
      setBulkSelectIds([]);
      loadData();
    } catch (err) {
      alert("Bulk approval failed: " + (err.response?.data?.error || err.message));
    }
  };

  // Handle select all checkbox
  const handleSelectAll = (e) => {
    const pageApprovableIds = currentRecords
      .filter(r => r.review_status === 'pending' && r.validation_status !== 'failed')
      .map(r => r.id);
    
    if (e.target.checked) {
      setBulkSelectIds(prev => {
        const newIds = [...prev];
        pageApprovableIds.forEach(id => {
          if (!newIds.includes(id)) newIds.push(id);
        });
        return newIds;
      });
    } else {
      setBulkSelectIds(prev => prev.filter(id => !pageApprovableIds.includes(id)));
    }
  };

  const handleSelectRecordCheckbox = (recordId) => {
    if (bulkSelectIds.includes(recordId)) {
      setBulkSelectIds(bulkSelectIds.filter(id => id !== recordId));
    } else {
      setBulkSelectIds([...bulkSelectIds, recordId]);
    }
  };

  return (
    <div className="min-h-screen bg-[#080d19] text-[#f1f5f9] flex flex-col font-sans">
      {/* Top Banner Header */}
      <header className="bg-[#0f172a] border-b border-[#1e293b] px-6 py-4 flex items-center justify-between shadow-lg">
        <div className="flex items-center space-x-3">
          <div className="bg-green-600 text-white p-2 rounded-lg flex items-center justify-center">
            <ShieldCheck className="h-6 w-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold tracking-tight text-white flex items-center">
              Breathe ESG <span className="ml-2 text-xs bg-green-950 text-green-400 border border-green-800 px-2 py-0.5 rounded-full font-semibold">Audit Engine v1.0</span>
            </h1>
            <p className="text-xs text-slate-400">Enterprise Data Ingestion & Audit Lock Platform</p>
          </div>
        </div>

        <div className="flex items-center space-x-6">
          <div className="text-right">
            <span className="block text-sm font-semibold text-slate-200">Acme Industrial Corp</span>
            <span className="text-xs text-green-400 font-medium">Tenant Tenant Isolation Enabled</span>
          </div>
          <div className="h-8 w-px bg-[#1e293b]"></div>
          <div className="flex items-center space-x-2">
            <div className="bg-slate-800 h-8 w-8 rounded-full flex items-center justify-center text-slate-300 font-bold text-sm">
              SA
            </div>
            <div>
              <span className="block text-xs font-semibold text-slate-300">Sustainability Analyst</span>
              <span className="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded">Write access</span>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 p-6 space-y-6 max-w-7xl mx-auto w-full">
        {/* KPI Dashboard Grid */}
        <section className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-5 shadow-sm relative overflow-hidden">
            <div className="absolute right-0 bottom-0 translate-x-3 translate-y-3 opacity-5">
              <BarChart3 className="h-32 w-32" />
            </div>
            <span className="text-xs text-slate-400 font-semibold block mb-1">TOTAL CERTIFIED EMISSIONS</span>
            <h2 className="text-3xl font-extrabold text-white">
              {metrics.total_co2e.toLocaleString(undefined, { maximumFractionDigits: 1 })} <span className="text-sm text-slate-400 font-normal">kg CO2e</span>
            </h2>
            <div className="mt-2 text-xs flex items-center text-green-400 font-medium">
              <Check className="h-4 w-4 mr-1" /> Ready for auditor lock
            </div>
          </div>

          <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-5 shadow-sm">
            <span className="text-xs text-slate-400 font-semibold block mb-1">EMISSIONS BY SCOPE</span>
            <div className="space-y-1.5 mt-2">
              <div className="flex justify-between text-xs items-center">
                <span className="text-slate-400 font-medium">Scope 1 (Direct Fuel)</span>
                <span className="text-white font-bold">{metrics.scope_1.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg</span>
              </div>
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-red-500 h-full rounded-full" style={{ width: `${(metrics.scope_1 / (metrics.total_co2e || 1)) * 100}%` }}></div>
              </div>
              
              <div className="flex justify-between text-xs items-center">
                <span className="text-slate-400 font-medium">Scope 2 (Electricity)</span>
                <span className="text-white font-bold">{metrics.scope_2.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg</span>
              </div>
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-amber-500 h-full rounded-full" style={{ width: `${(metrics.scope_2 / (metrics.total_co2e || 1)) * 100}%` }}></div>
              </div>
              
              <div className="flex justify-between text-xs items-center">
                <span className="text-slate-400 font-medium">Scope 3 (Travel / supply)</span>
                <span className="text-white font-bold">{metrics.scope_3.toLocaleString(undefined, { maximumFractionDigits: 1 })} kg</span>
              </div>
              <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden">
                <div className="bg-blue-500 h-full rounded-full" style={{ width: `${(metrics.scope_3 / (metrics.total_co2e || 1)) * 100}%` }}></div>
              </div>
            </div>
          </div>

          <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-5 shadow-sm">
            <span className="text-xs text-slate-400 font-semibold block mb-1">REVIEW WORKFLOW QUEUE</span>
            <div className="grid grid-cols-2 gap-4 mt-2">
              <div>
                <span className="text-xs text-slate-400 block">Pending Review</span>
                <span className="text-2xl font-bold text-blue-400">{metrics.counts.pending}</span>
              </div>
              <div>
                <span className="text-xs text-slate-400 block">Approved & Locked</span>
                <span className="text-2xl font-bold text-green-400">{metrics.counts.approved}</span>
              </div>
            </div>
            <div className="mt-2 text-[10px] text-slate-500">Locked rows are immutable for audit logs.</div>
          </div>

          <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-5 shadow-sm">
            <span className="text-xs text-slate-400 font-semibold block mb-1">INGESTED DATA INTEGRITY HEALTH</span>
            <div className="flex items-center space-x-4 mt-2">
              <div className="text-3xl font-extrabold text-white">
                {metrics.counts.total > 0
                  ? Math.round(((metrics.counts.total - metrics.counts.failed) / metrics.counts.total) * 100)
                  : 100}%
              </div>
              <div className="flex-1 space-y-1">
                <div className="flex justify-between text-[10px]">
                  <span className="text-red-400 font-medium">Critical Errors: {metrics.counts.failed}</span>
                  <span className="text-amber-400 font-medium">Suspicious Rows: {metrics.counts.suspicious}</span>
                </div>
                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden flex">
                  <div className="bg-red-500" style={{ width: `${(metrics.counts.failed / (metrics.counts.total || 1)) * 100}%` }}></div>
                  <div className="bg-amber-500" style={{ width: `${(metrics.counts.suspicious / (metrics.counts.total || 1)) * 100}%` }}></div>
                  <div className="bg-green-500 flex-1"></div>
                </div>
              </div>
            </div>
            <span className="block text-[10px] text-slate-500 mt-2">Errors block approval. Warnings require comment override.</span>
          </div>
        </section>

        {/* Data Ingestion Control Center */}
        <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* File Uploader */}
          <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-5 shadow-sm md:col-span-2">
            <h3 className="text-sm font-bold text-white mb-3 flex items-center">
              <Upload className="h-4 w-4 mr-2 text-green-500" />
              INGEST CSV EXPORTS (SAP / UTILITY PORTALS)
            </h3>
            
            <form onSubmit={handleFileUpload} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-400 font-semibold mb-1">Target Ingestion Pipeline</label>
                  <select
                    className="w-full bg-[#1f2937] border border-[#374151] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-green-500"
                    value={selectedUploadSource}
                    onChange={(e) => setSelectedUploadSource(e.target.value)}
                  >
                    {dataSources.map(ds => (
                      <option key={ds.id} value={ds.id}>
                        {ds.name} ({ds.source_type === 'sap_fuel' ? 'German CSV' : ds.source_type === 'utility_electricity' ? 'Electricity Portal' : 'API Sync'})
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs text-slate-400 font-semibold mb-1 font-mono">Select Export File (.csv)</label>
                  <input
                    id="csv-file-input"
                    type="file"
                    accept=".csv"
                    className="w-full bg-[#1f2937] border border-[#374151] rounded-lg px-3 py-1 text-sm text-slate-300 focus:outline-none"
                    onChange={(e) => setSelectedFile(e.target.files[0])}
                  />
                </div>
              </div>

              <div className="flex items-center justify-between pt-2">
                <div className="text-xs">
                  {uploadStatus.state === 'loading' && <span className="text-blue-400 flex items-center"><RefreshCw className="h-3 w-3 animate-spin mr-1.5" />{uploadStatus.msg}</span>}
                  {uploadStatus.state === 'success' && <span className="text-green-400 flex items-center"><CheckCircle className="h-3.5 w-3.5 mr-1.5" />{uploadStatus.msg}</span>}
                  {uploadStatus.state === 'error' && <span className="text-red-400 flex items-center font-semibold"><XCircle className="h-3.5 w-3.5 mr-1.5" />{uploadStatus.msg}</span>}
                </div>
                <button
                  type="submit"
                  disabled={uploadStatus.state === 'loading'}
                  className="bg-green-600 hover:bg-green-500 disabled:bg-slate-800 text-white font-semibold text-xs px-4 py-2.5 rounded-lg flex items-center transition shadow"
                >
                  <Database className="h-3.5 w-3.5 mr-1.5" /> Run Normalization Pipeline
                </button>
              </div>
            </form>
          </div>

          {/* REST API Sync triggers */}
          <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-5 shadow-sm flex flex-col justify-between">
            <div>
              <h3 className="text-sm font-bold text-white mb-1 flex items-center">
                <RefreshCw className="h-4 w-4 mr-2 text-blue-500" />
                MOCK TRAVEL PLATFORM SYNC
              </h3>
              <p className="text-xs text-slate-400 mb-4">Pull latest transactions from mock corporate travel API (flights, hotels, ground transport).</p>
              
              <div className="space-y-3">
                {dataSources.filter(ds => ds.source_type === 'corporate_travel').map(ds => (
                  <div key={ds.id} className="flex items-center justify-between p-3 bg-[#1f2937] rounded-lg border border-[#374151]">
                    <div>
                      <span className="block text-xs font-bold text-white">{ds.name}</span>
                      <span className="text-[10px] text-slate-400 font-mono">GET /api/external/travel-data/</span>
                    </div>
                    <button
                      onClick={() => handleApiSync(ds.id)}
                      disabled={syncingSourceId === ds.id}
                      className="bg-blue-600 hover:bg-blue-500 disabled:bg-slate-800 text-white text-[10px] font-bold px-3 py-2 rounded transition flex items-center"
                    >
                      {syncingSourceId === ds.id ? (
                        <>
                          <RefreshCw className="h-3 w-3 animate-spin mr-1" />
                          Syncing
                        </>
                      ) : (
                        <>
                          <RefreshCw className="h-3 w-3 mr-1" />
                          Sync API
                        </>
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </div>
            <div className="text-[10px] text-slate-500 mt-4">Calculates flight distances via Great-Circle coordinates if missing.</div>
          </div>
        </section>

        {/* Filters and Search Bar */}
        <section className="bg-[#111827] border border-[#1f2937] rounded-xl p-4 flex flex-wrap gap-4 items-center justify-between">
          <div className="flex flex-wrap gap-3 items-center">
            <span className="text-xs text-slate-400 font-bold uppercase tracking-wider flex items-center mr-1">
              <Filter className="h-3.5 w-3.5 mr-1.5" /> Filters:
            </span>

            {/* Filter Scope */}
            <select
              className="bg-[#1f2937] border border-[#374151] text-xs text-white rounded-lg px-2.5 py-1.5 focus:outline-none"
              value={filterScope}
              onChange={(e) => setFilterScope(e.target.value)}
            >
              <option value="">All Scopes</option>
              <option value="1">Scope 1 - Fuel</option>
              <option value="2">Scope 2 - Grid</option>
              <option value="3">Scope 3 - Travel</option>
            </select>

            {/* Filter Source Type */}
            <select
              className="bg-[#1f2937] border border-[#374151] text-xs text-white rounded-lg px-2.5 py-1.5 focus:outline-none"
              value={filterSourceType}
              onChange={(e) => setFilterSourceType(e.target.value)}
            >
              <option value="">All Source Types</option>
              <option value="sap_fuel">SAP Export</option>
              <option value="utility_electricity">Utility Portal</option>
              <option value="corporate_travel">Travel API</option>
            </select>

            {/* Filter Validation Status */}
            <select
              className="bg-[#1f2937] border border-[#374151] text-xs text-white rounded-lg px-2.5 py-1.5 focus:outline-none"
              value={filterValStatus}
              onChange={(e) => setFilterValStatus(e.target.value)}
            >
              <option value="">All Integrity Statuses</option>
              <option value="valid">Valid (Passed)</option>
              <option value="suspicious">Suspicious (Warning)</option>
              <option value="failed">Failed (Error)</option>
            </select>

            {/* Filter Review Status */}
            <select
              className="bg-[#1f2937] border border-[#374151] text-xs text-white rounded-lg px-2.5 py-1.5 focus:outline-none"
              value={filterRevStatus}
              onChange={(e) => setFilterRevStatus(e.target.value)}
            >
              <option value="">All Review Statuses</option>
              <option value="pending">Pending analyst</option>
              <option value="approved">Approved & locked</option>
              <option value="rejected">Rejected (Needs fix)</option>
            </select>
          </div>

          <div className="relative w-full md:w-64">
            <span className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-3.5 w-3.5 text-slate-400" />
            </span>
            <input
              type="text"
              className="w-full bg-[#1f2937] border border-[#374151] text-xs text-white rounded-lg pl-9 pr-4 py-1.5 focus:outline-none focus:border-green-500"
              placeholder="Search plant, activity, unit..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
        </section>

        {/* Review Queue and Audit Logs Grid */}
        <section className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Main Table (Col 3) */}
          <div className="bg-[#111827] border border-[#1f2937] rounded-xl overflow-hidden shadow-sm lg:col-span-3">
            <div className="px-5 py-4 border-b border-[#1f2937] flex items-center justify-between">
              <h3 className="text-sm font-bold text-white flex items-center">
                <ClipboardList className="h-4 w-4 mr-2 text-green-500" />
                NORMALIZED DATA AUDIT REVIEW QUEUE ({records.length} records)
              </h3>
              
              {bulkSelectIds.length > 0 && (
                <button
                  onClick={handleBulkApprove}
                  className="bg-green-600 hover:bg-green-500 text-white text-xs font-bold px-3 py-1.5 rounded transition shadow flex items-center"
                >
                  <Check className="h-3.5 w-3.5 mr-1" /> Bulk Approve ({bulkSelectIds.length} Selected)
                </button>
              )}
            </div>

            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-[#0f172a] text-[10px] text-slate-400 font-bold uppercase border-b border-[#1f2937]">
                    <th className="py-3.5 px-4 w-10">
                      <input
                        type="checkbox"
                        className="rounded bg-slate-800 border-slate-700 focus:ring-green-500"
                        onChange={handleSelectAll}
                        checked={currentRecords.length > 0 && currentRecords.filter(r => r.review_status === 'pending' && r.validation_status !== 'failed').every(r => bulkSelectIds.includes(r.id))}
                      />
                    </th>
                    <th className="py-3.5 px-3">Date</th>
                    <th className="py-3.5 px-3">Activity Type</th>
                    <th className="py-3.5 px-3">Facility/Plant</th>
                    <th className="py-3.5 px-3 text-right">Raw Amount</th>
                    <th className="py-3.5 px-3 text-right">Normalized Amount</th>
                    <th className="py-3.5 px-3 text-right">Calculated CO2e</th>
                    <th className="py-3.5 px-3 text-center">Integrity</th>
                    <th className="py-3.5 px-3 text-center">Review</th>
                    <th className="py-3.5 px-4 w-12"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#1e293b] text-xs">
                  {currentRecords.length === 0 ? (
                    <tr>
                      <td colSpan="10" className="py-8 text-center text-slate-400">
                        No records match the current filters. Clean or sync new data to start.
                      </td>
                    </tr>
                  ) : (
                    currentRecords.map(record => (
                      <tr
                        key={record.id}
                        className={`hover:bg-[#1f2937]/50 cursor-pointer transition ${selectedRecord?.id === record.id ? 'bg-[#1f2937]/80' : ''}`}
                        onClick={() => setSelectedRecord(record)}
                      >
                        <td className="py-3 px-4" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            disabled={record.review_status !== 'pending' || record.validation_status === 'failed'}
                            checked={bulkSelectIds.includes(record.id)}
                            onChange={() => handleSelectRecordCheckbox(record.id)}
                            className="rounded bg-slate-800 border-slate-700 disabled:opacity-30 focus:ring-green-500 text-green-600"
                          />
                        </td>
                        <td className="py-3 px-3 text-slate-300 font-mono whitespace-nowrap">{record.transaction_date}</td>
                        <td className="py-3 px-3 capitalize">
                          <span className="block text-slate-200 font-semibold">{record.activity_type.replace('_', ' ')}</span>
                          <span className="text-[10px] text-slate-400">Scope {record.scope_category}</span>
                        </td>
                        <td className="py-3 px-3 font-semibold text-slate-300 max-w-[120px] truncate">{record.facility_or_plant || '—'}</td>
                        <td className="py-3 px-3 text-right font-mono">
                          {parseFloat(record.raw_quantity).toLocaleString(undefined, { maximumFractionDigits: 2 })} {record.raw_unit}
                        </td>
                        <td className="py-3 px-3 text-right font-mono">
                          {parseFloat(record.normalized_quantity).toLocaleString(undefined, { maximumFractionDigits: 2 })} {record.normalized_unit}
                        </td>
                        <td className="py-3 px-3 text-right font-mono font-bold text-white">
                          {parseFloat(record.calculated_co2e).toLocaleString(undefined, { maximumFractionDigits: 1 })} kg
                        </td>
                        <td className="py-3 px-3 text-center">
                          {record.validation_status === 'valid' && (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-950/40 text-emerald-400 border border-emerald-800/40">PASSED</span>
                          )}
                          {record.validation_status === 'suspicious' && (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-amber-950/40 text-amber-400 border border-amber-800/40">WARNING</span>
                          )}
                          {record.validation_status === 'failed' && (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-red-950/40 text-red-400 border border-red-800/40">ERROR</span>
                          )}
                        </td>
                        <td className="py-3 px-3 text-center">
                          {record.review_status === 'pending' && (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-blue-950/40 text-blue-400 border border-blue-800/40">PENDING</span>
                          )}
                          {record.review_status === 'approved' && (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-green-950/40 text-green-400 border border-green-800/40 flex items-center justify-center space-x-1">
                              <Lock className="h-2.5 w-2.5" />
                              <span>LOCKED</span>
                            </span>
                          )}
                          {record.review_status === 'rejected' && (
                            <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-red-950/40 text-red-400 border border-red-800/40">REJECTED</span>
                          )}
                        </td>
                        <td className="py-3 px-4 text-center">
                          <ChevronRight className="h-4 w-4 text-slate-500" />
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {records.length > 0 && (
              <div className="px-5 py-3 border-t border-[#1f2937] flex items-center justify-between bg-[#0f172a]/20 text-xs">
                <span className="text-slate-400">
                  Showing <span className="text-white font-medium">{indexOfFirstRecord + 1}</span> to{' '}
                  <span className="text-white font-medium">
                    {Math.min(indexOfLastRecord, records.length)}
                  </span>{' '}
                  of <span className="text-white font-medium">{records.length}</span> records
                </span>
                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                    disabled={currentPage === 1}
                    className="p-1.5 rounded bg-[#1f2937] hover:bg-[#374151] disabled:opacity-40 disabled:hover:bg-[#1f2937] text-white transition flex items-center cursor-pointer disabled:cursor-not-allowed"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </button>
                  <span className="text-slate-300">
                    Page <span className="text-white font-bold">{currentPage}</span> of{' '}
                    <span className="text-white font-bold">{totalPages}</span>
                  </span>
                  <button
                    onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                    disabled={currentPage === totalPages}
                    className="p-1.5 rounded bg-[#1f2937] hover:bg-[#374151] disabled:opacity-40 disabled:hover:bg-[#1f2937] text-white transition flex items-center cursor-pointer disabled:cursor-not-allowed"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Audit Logs Sidebar (Col 1) */}
          <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-4 shadow-sm h-[550px] flex flex-col justify-between">
            <div>
              <h3 className="text-xs font-bold text-white uppercase tracking-wider mb-3 flex items-center pb-2 border-b border-[#1f2937]">
                <ClipboardList className="h-4 w-4 mr-1 text-slate-400" /> SYSTEM AUDIT LOG TRAIL
              </h3>
              
              <div className="space-y-3 overflow-y-auto max-h-[420px] pr-1">
                {audits.length === 0 ? (
                  <p className="text-xs text-slate-500 text-center py-4">No audit events logged yet.</p>
                ) : (
                  audits.map(log => (
                    <div key={log.id} className="p-2.5 bg-[#1f2937]/50 rounded-lg border border-[#374151]/40 text-[11px] leading-relaxed">
                      <div className="flex justify-between items-center mb-1">
                        <span className="font-bold text-slate-300 font-mono text-[9px] bg-slate-800 px-1 py-0.5 rounded">
                          {log.action}
                        </span>
                        <span className="text-[9px] text-slate-500">{new Date(log.created_at).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-slate-400">
                        {log.action === 'UPLOAD' && `CSV file '${log.changes.filename}' ingested by ${log.username}. normalized ${log.changes.total_rows} rows.`}
                        {log.action === 'NORMALIZE' && `Calculated CO2e for record. CO2e: ${parseFloat(log.changes.calculated_co2e).toFixed(1)} kg`}
                        {log.action === 'APPROVE' && `Record audit-locked by ${log.username}. Reason: ${log.changes.reason || 'None'}`}
                        {log.action === 'REJECT' && `Record rejected by ${log.username}. Reason: ${log.changes.reason}`}
                      </p>
                    </div>
                  ))
                )}
              </div>
            </div>
            
            <div className="text-[10px] text-slate-500 text-center pt-2 border-t border-[#1f2937]">
              Immutable logging active
            </div>
          </div>
        </section>
      </main>

      {/* Slide-out details drawer */}
      {selectedRecord && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-xs z-50 flex justify-end transition-opacity">
          <div className="w-full max-w-lg bg-[#0e1320] h-full shadow-2xl flex flex-col justify-between border-l border-[#1f2937] animate-slide-in">
            {/* Header */}
            <div className="p-5 border-b border-[#1f2937] flex justify-between items-center bg-[#151c2c]">
              <div>
                <span className="text-[10px] font-bold text-green-400 uppercase tracking-widest block mb-0.5">RECORD DETAILS & AUDIT LOG</span>
                <h3 className="text-base font-bold text-white flex items-center capitalize">
                  {selectedRecord.activity_type.replace('_', ' ')}
                  <span className="ml-2 text-xs font-normal text-slate-400 mr-3">Scope {selectedRecord.scope_category}</span>
                  {selectedRecord.review_status === 'approved' && (
                    <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-green-950/40 text-green-400 border border-green-800/40">LOCKED</span>
                  )}
                  {selectedRecord.review_status === 'rejected' && (
                    <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-red-950/40 text-red-400 border border-red-800/40">REJECTED</span>
                  )}
                  {selectedRecord.review_status === 'pending' && (
                    <span className="inline-flex px-2 py-0.5 rounded text-[10px] font-bold bg-blue-950/40 text-blue-400 border border-blue-800/40">PENDING</span>
                  )}
                </h3>
              </div>
              <button
                onClick={() => { setSelectedRecord(null); setReviewReason(''); }}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {/* Content Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-6">
              
              {/* Validation Alerts */}
              {selectedRecord.issues && selectedRecord.issues.length > 0 && (
                <div className="bg-slate-900 border border-[#1f2937] rounded-xl p-4 space-y-2">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">INTEGRITY VALIDATION ISSUES ({selectedRecord.issues.length})</span>
                  
                  <div className="space-y-2.5">
                    {selectedRecord.issues.map(issue => (
                      <div key={issue.id} className={`p-3 rounded-lg border flex items-start space-x-2.5 ${issue.severity === 'error' ? 'bg-red-950/20 border-red-800/40 text-red-300' : 'bg-amber-950/20 border-amber-800/40 text-amber-300'}`}>
                        {issue.severity === 'error' ? (
                          <ShieldAlert className="h-4 w-4 shrink-0 text-red-400 mt-0.5" />
                        ) : (
                          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400 mt-0.5" />
                        )}
                        <div className="text-xs">
                          <span className="font-bold uppercase block text-[9px] tracking-wide mb-0.5">
                            {issue.severity === 'error' ? 'Critical Error (Approval Blocked)' : 'Suspicious Check (Justification Required)'}
                          </span>
                          {issue.message}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Normalization Math Card */}
              <div className="bg-slate-900 border border-[#1f2937] rounded-xl p-4 space-y-3.5">
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">NORMALIZATION CALCULATION PATH</span>
                
                <div className="grid grid-cols-2 gap-4 text-xs">
                  <div className="bg-[#151c2c] p-2.5 rounded-lg border border-[#374151]/30">
                    <span className="text-[10px] text-slate-500 block">Raw Value Ingested</span>
                    <span className="font-bold text-slate-200 font-mono text-sm">
                      {parseFloat(selectedRecord.raw_quantity).toLocaleString()} {selectedRecord.raw_unit}
                    </span>
                  </div>
                  <div className="bg-[#151c2c] p-2.5 rounded-lg border border-[#374151]/30">
                    <span className="text-[10px] text-slate-500 block">Normalized Quantity</span>
                    <span className="font-bold text-slate-200 font-mono text-sm">
                      {parseFloat(selectedRecord.normalized_quantity).toLocaleString()} {selectedRecord.normalized_unit}
                    </span>
                  </div>
                  <div className="bg-[#151c2c] p-2.5 rounded-lg border border-[#374151]/30">
                    <span className="text-[10px] text-slate-500 block">Emission Factor Applied</span>
                    <span className="font-bold text-slate-200 font-mono text-sm">
                      {parseFloat(selectedRecord.emission_factor).toFixed(4)} kg/unit
                    </span>
                  </div>
                  <div className="bg-[#151c2c] p-2.5 rounded-lg border border-[#374151]/30">
                    <span className="text-[10px] text-slate-500 block">Scope 1/2/3 Target</span>
                    <span className="font-bold text-green-400 text-sm">
                      Scope {selectedRecord.scope_category} Activity
                    </span>
                  </div>
                </div>

                <div className="p-3 bg-green-950/20 border border-green-800/20 rounded-lg flex items-center justify-between text-xs">
                  <div>
                    <span className="text-[9px] text-slate-400 block font-mono">CALCULATED AUDIT CO2e</span>
                    <span className="text-xs font-semibold text-slate-400">
                      {parseFloat(selectedRecord.normalized_quantity).toLocaleString()} * {parseFloat(selectedRecord.emission_factor).toFixed(4)} =
                    </span>
                  </div>
                  <span className="text-lg font-bold text-white font-mono">
                    {parseFloat(selectedRecord.calculated_co2e).toLocaleString(undefined, { maximumFractionDigits: 2 })} kg CO2e
                  </span>
                </div>
              </div>

              {/* Source-of-Truth exact raw JSON record */}
              <div className="bg-[#111827] border border-[#1f2937] rounded-xl p-4 space-y-2">
                <div className="flex justify-between items-center">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">SOURCE OF TRUTH RAW RECORD JSON</span>
                  <span className="text-[9px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded font-mono uppercase">{selectedRecord.source_type}</span>
                </div>
                <pre className="bg-[#0b0f19] p-3 rounded-lg text-[10px] font-mono text-green-400 overflow-x-auto border border-[#1e293b] leading-relaxed max-h-48">
                  {JSON.stringify(selectedRecord.raw_data, null, 2)}
                </pre>
                <span className="block text-[9px] text-slate-500 italic">This immutable JSON is preserved exactly as it came from the enterprise exporter.</span>
              </div>

              {/* History information if already reviewed */}
              {selectedRecord.review_status !== 'pending' && (
                <div className="bg-slate-900 border border-[#1f2937] rounded-xl p-4 space-y-2 text-xs">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block">REVIEW HISTORY</span>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400">Decision Status:</span>
                    <span className="font-bold capitalize text-white">{selectedRecord.review_status}</span>
                  </div>
                  {selectedRecord.last_decision_by && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400">Reviewed By:</span>
                      <span className="font-bold text-white">{selectedRecord.last_decision_by}</span>
                    </div>
                  )}
                  {selectedRecord.last_decision_reason && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400 font-medium">Justification:</span>
                      <span className="font-semibold text-white text-right max-w-[220px] break-words">{selectedRecord.last_decision_reason}</span>
                    </div>
                  )}
                  {selectedRecord.approved_at && selectedRecord.review_status === 'approved' && (
                    <div className="flex items-center justify-between">
                      <span className="text-slate-400">Reviewed At:</span>
                      <span className="font-bold font-mono text-white">{new Date(selectedRecord.approved_at).toLocaleString()}</span>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Footer Analyst Controls */}
            <div className="p-5 border-t border-[#1f2937] bg-[#151c2c] space-y-4">
              {selectedRecord.is_locked ? (
                <div className="flex items-center justify-center space-x-2 py-3 bg-[#080d19] border border-green-800/30 rounded-lg text-xs text-green-400 font-bold uppercase tracking-wider">
                  <Lock className="h-4 w-4" />
                  <span>RECORD IS IMMUTABLE (AUDIT LOCKED)</span>
                </div>
              ) : (
                <div className="space-y-3">
                  <div>
                    <label className="block text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-1">
                      Analyst Review Override Justification Reason
                    </label>
                    <textarea
                      className="w-full bg-[#0b0f19] border border-[#374151] rounded-lg px-3 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-green-500 resize-none h-16"
                      placeholder="Required for rejections, duplicate overrides, or large quantity justifications..."
                      value={reviewReason}
                      onChange={(e) => setReviewReason(e.target.value)}
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <button
                      onClick={() => handleReject(selectedRecord.id)}
                      className="bg-red-950/40 hover:bg-red-900/40 text-red-400 border border-red-800/40 font-bold text-xs py-2.5 rounded-lg transition"
                    >
                      Reject Transaction
                    </button>
                    <button
                      onClick={() => handleApprove(selectedRecord.id)}
                      disabled={selectedRecord.validation_status === 'failed'}
                      className="bg-green-600 hover:bg-green-500 disabled:bg-slate-800 disabled:text-slate-500 font-bold text-xs py-2.5 rounded-lg text-white transition flex items-center justify-center"
                    >
                      <Lock className="h-3.5 w-3.5 mr-1.5" /> Approve & Audit Lock
                    </button>
                  </div>
                  {selectedRecord.validation_status === 'failed' && (
                    <span className="block text-[10px] text-red-400 text-center font-semibold">
                      * Cannot approve record with active blocking error validation issues.
                    </span>
                  )}
                </div>
              )}
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
