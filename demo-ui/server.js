const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { execFile } = require('child_process');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Base path to the search reports (Environment variable or relative path)
const REPORTS_BASE = process.env.REPORTS_DIR || path.join(
  __dirname, '..',
  'Search Reports-20260730T080443Z-1-001',
  'Search Reports'
);

// Cloud Storage URL (Cloudflare R2, AWS S3, Firebase, etc.)
const PDF_BASE_URL = process.env.PDF_BASE_URL || process.env.CLOUDFLARE_R2_URL;

// Serve static frontend
app.use(express.static(path.join(__dirname, 'public')));

// Serve PDF files from local reports directory OR redirect to Cloud Storage (Cloudflare R2 / S3)
app.use('/pdfs', (req, res, next) => {
  if (PDF_BASE_URL) {
    const targetUrl = `${PDF_BASE_URL.replace(/\/$/, '')}${req.url}`;
    return res.redirect(targetUrl);
  }
  next();
}, express.static(REPORTS_BASE));

// ─── Data Mapping ────────────────────────────────────────────────

// Map persons to their directories across all categories
const PERSON_MAP = {
  'G Janardhan Reddy': {
    litigation: {
      'District Court': [
        'Litigation Search/District Course Case details - Persons/G Janardhan Reddy'
      ],
      'High Court - Karnataka': [
        'Litigation Search/High Court Case details - Persons/G Janathan Reddy/Karnataka'
      ],
      'High Court - Telangana': [
        'Litigation Search/High Court Case details - Persons/G Janathan Reddy/Telangana'
      ]
    }
  },
  'G Veera Reddy': {
    litigation: {
      'District Court': [
        'Litigation Search/District Course Case details - Persons/G Veera Reddy'
      ]
    }
  },
  'G. Kanaka Durga': {
    litigation: {
      'District Court': [
        'Litigation Search/District Course Case details - Persons/G. Kanaka Durga'
      ]
    }
  },
  'G Laxmi Reddy': {
    litigation: {
      'DRT': [
        'Litigation Search/DRT/Persons/G Laxmi Reddy'
      ]
    }
  }
};

const ENTITY_MAP = {
  'Tulip Data Centre Services Private Limited': {
    roc: {
      'Annual Returns & Balance Sheets': [
        'ROC Search/Tulip Data Centre Services Private Limited/Annual Returns and Balance Sheet eForms'
      ],
      'Certificates': [
        'ROC Search/Tulip Data Centre Services Private Limited/Certificates'
      ],
      'Charge Sheets': [
        'ROC Search/Tulip Data Centre Services Private Limited/Charge Sheets'
      ],
      'Incorporation Documents': [
        'ROC Search/Tulip Data Centre Services Private Limited/Incorporation Documents'
      ]
    },
    litigation: {
      'District Court': [
        'Litigation Search/District Court Case Details - Entities/Tulip Data services'
      ],
      'High Court - Delhi': [
        'Litigation Search/High court Case Details - Entities/Delhi High court/Tulip Data Centre Services Private Limited'
      ],
      'DRT': [
        'Litigation Search/DRT/Entities/Tulip Data services'
      ]
    }
  },
  'Space World Group LLP': {
    roc: {
      'Annual Returns & Balance Sheets': [
        'ROC Search/Space World Group LLP/Annual Returns and Balance Sheet eForms'
      ],
      'Certificates': [
        'ROC Search/Space World Group LLP/Certificates'
      ],
      'Charge Sheets': [
        'ROC Search/Space World Group LLP/Charge sheets'
      ]
    },
    litigation: {
      'High Court - Delhi': [
        'Litigation Search/High court Case Details - Entities/Delhi High court/Space World Group LLP'
      ]
    }
  },
  'Space World Data Centre Private Limited': {
    roc: {
      'Annual Returns & Balance Sheets': [
        'ROC Search/Space World Data Centre Private Limited/Annual Returns and Balance Sheet eForms'
      ],
      'Certificates': [
        'ROC Search/Space World Data Centre Private Limited/Certificates'
      ],
      'Charge Sheets': [
        'ROC Search/Space World Data Centre Private Limited/Charge sheets'
      ],
      'Incorporation': [
        'ROC Search/Space World Data Centre Private Limited/Incorporation'
      ]
    },
    litigation: {
      'High Court - Karnataka': [
        'Litigation Search/High court Case Details - Entities/Karnataka HC'
      ]
    }
  },
  'GVR Electro Technics Pvt Ltd': {
    roc: {
      'Annual Returns': [
        'ROC Search/GVR ELECTRO TECHNICS PVT LTD/Annual'
      ],
      'Certificates': [
        'ROC Search/GVR ELECTRO TECHNICS PVT LTD/Certificates'
      ],
      'Charge Sheets': [
        'ROC Search/GVR ELECTRO TECHNICS PVT LTD/Charge sheets'
      ],
      'Incorporation': [
        'ROC Search/GVR ELECTRO TECHNICS PVT LTD/Incorporation'
      ]
    }
  },
  'SADA IT Parks Private Limited': {
    roc: {
      'Annual Returns': [
        'ROC Search/SADA IT PARKS PRIVATE LIMITED/Annual returns'
      ],
      'Certificates': [
        'ROC Search/SADA IT PARKS PRIVATE LIMITED/Certificate'
      ],
      'Charge Sheets': [
        'ROC Search/SADA IT PARKS PRIVATE LIMITED/Charge Sheets'
      ],
      'Incorporation': [
        'ROC Search/SADA IT PARKS PRIVATE LIMITED/Incorporation'
      ]
    }
  }
};

// Load optional manifest for remote/cloud deployment fallback
let MANIFEST = null;
const MANIFEST_PATH = path.join(__dirname, 'reports-manifest.json');
if (fs.existsSync(MANIFEST_PATH)) {
  try {
    MANIFEST = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'));
    console.log(`Loaded reports manifest with ${Object.keys(MANIFEST).length} categories.`);
  } catch (err) {
    console.error('Failed to parse reports-manifest.json:', err);
  }
}

// ─── Helper: Recursively get PDFs from a directory ───────────────

function getPdfsFromDir(dirPath) {
  const results = [];
  if (fs.existsSync(dirPath)) {
    const items = fs.readdirSync(dirPath, { withFileTypes: true });
    for (const item of items) {
      const fullPath = path.join(dirPath, item.name);
      if (item.isDirectory()) {
        results.push(...getPdfsFromDir(fullPath));
      } else if (item.name.toLowerCase().endsWith('.pdf')) {
        // Build a URL-safe relative path from REPORTS_BASE
        const relativePath = path.relative(REPORTS_BASE, fullPath).replace(/\\/g, '/');
        results.push({
          name: item.name,
          url: '/pdfs/' + encodeURIComponent(relativePath).replace(/%2F/g, '/'),
          size: fs.statSync(fullPath).size
        });
      }
    }
    return results;
  }

  // Fallback to manifest if local dir does not exist (e.g., cloud deployment on Render)
  if (MANIFEST) {
    const relativeKey = path.relative(REPORTS_BASE, dirPath).replace(/\\/g, '/');
    for (const [key, files] of Object.entries(MANIFEST)) {
      if (key === relativeKey || key.startsWith(relativeKey + '/')) {
        for (const file of files) {
          results.push({
            name: file.name,
            url: '/pdfs/' + encodeURIComponent(file.relativePath).replace(/%2F/g, '/'),
            size: file.size || 0
          });
        }
      }
    }
  }

  return results;
}

// ─── API: Get list of names ─────────────────────────────────────

app.get('/api/names', (req, res) => {
  const type = req.query.type;
  if (type === 'person') {
    res.json({ names: Object.keys(PERSON_MAP) });
  } else if (type === 'entity') {
    res.json({ names: Object.keys(ENTITY_MAP) });
  } else {
    res.status(400).json({ error: 'Invalid type. Use person or entity.' });
  }
});

// ─── API: Search for documents by name ──────────────────────────

app.get('/api/search', (req, res) => {
  const { type, name } = req.query;

  // Global Asset Search Details
  if (type === 'asset') {
    const assetDir = path.join(REPORTS_BASE, 'Asset based search');
    const pdfs = getPdfsFromDir(assetDir);
    return res.json({
      name: 'Global Asset Details',
      type: 'asset',
      categories: {
        asset: {
          'CERSAI Asset Search Report': pdfs
        }
      }
    });
  }

  // Global Debtor Search Reports
  if (type === 'debtor') {
    const debtorDir = path.join(REPORTS_BASE, 'Debtor based search - Entities');
    const pdfs = getPdfsFromDir(debtorDir);
    return res.json({
      name: 'Debtor Search Reports (All Entities)',
      type: 'debtor',
      categories: {
        debtor: {
          'CERSAI Debtor Search Details': pdfs
        }
      }
    });
  }

  if (!type || !name) {
    return res.status(400).json({ error: 'Both type and name are required.' });
  }

  const map = type === 'person' ? PERSON_MAP : ENTITY_MAP;
  const entry = map[name];

  if (!entry) {
    return res.status(404).json({ error: `No data found for "${name}".` });
  }

  const result = {};

  // For each top-level category (roc, litigation)
  for (const [category, subCategories] of Object.entries(entry)) {
    result[category] = {};

    for (const [subCategory, dirPaths] of Object.entries(subCategories)) {
      const pdfs = [];
      for (const dirPath of dirPaths) {
        const fullDirPath = path.join(REPORTS_BASE, dirPath);
        pdfs.push(...getPdfsFromDir(fullDirPath));
      }
      if (pdfs.length > 0) {
        result[category][subCategory] = pdfs;
      }
    }
  }

  res.json({
    name,
    type,
    categories: result
  });
});

// ─── API: Get summary stats ─────────────────────────────────────

app.get('/api/stats', (req, res) => {
  let totalPdfs = 0;
  if (fs.existsSync(REPORTS_BASE)) {
    const countPdfs = (dir) => {
      const items = fs.readdirSync(dir, { withFileTypes: true });
      for (const item of items) {
        if (item.isDirectory()) {
          countPdfs(path.join(dir, item.name));
        } else if (item.name.toLowerCase().endsWith('.pdf')) {
          totalPdfs++;
        }
      }
    };
    countPdfs(REPORTS_BASE);
  } else if (MANIFEST) {
    const uniqueFiles = new Set();
    for (const files of Object.values(MANIFEST)) {
      for (const f of files) {
        uniqueFiles.add(f.relativePath);
      }
    }
    totalPdfs = uniqueFiles.size;
  }

  res.json({
    totalPersons: Object.keys(PERSON_MAP).length,
    totalEntities: Object.keys(ENTITY_MAP).length,
    totalDocuments: totalPdfs
  });
});

// ─── API: AI Chatbot Endpoint ───────────────────────────────────

// Path to Python executable (Cross-platform support for Linux/Docker and Windows)
function getPythonExecutable() {
  if (process.env.PYTHON_PATH) return process.env.PYTHON_PATH;
  const winVenv = path.join(__dirname, '..', 'venv', 'Scripts', 'python.exe');
  if (fs.existsSync(winVenv)) return winVenv;
  const linuxVenv = path.join(__dirname, '..', 'venv', 'bin', 'python');
  if (fs.existsSync(linuxVenv)) return linuxVenv;
  return process.platform === 'win32' ? 'python' : 'python3';
}

function runPythonChatbot(prompt, callback) {
  const pyCmd = getPythonExecutable();
  const scriptPath = path.join(__dirname, '..', 'chatbot.py');
  const options = {
    cwd: path.join(__dirname, '..'),
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  };

  execFile(pyCmd, [scriptPath, prompt], options, (error, stdout, stderr) => {
    if (error && (error.code === 'ENOENT' || error.message.includes('ENOENT'))) {
      const fallbackCmd = pyCmd === 'python3' ? 'python' : 'python3';
      console.log(`Primary python '${pyCmd}' failed with ENOENT. Retrying with fallback '${fallbackCmd}'...`);
      execFile(fallbackCmd, [scriptPath, prompt], options, callback);
    } else {
      callback(error, stdout, stderr);
    }
  });
}

app.post('/api/chat', (req, res) => {
  const { prompt } = req.body;
  if (!prompt || typeof prompt !== 'string') {
    return res.status(400).json({ error: 'Prompt string is required.' });
  }

  runPythonChatbot(prompt, (error, stdout, stderr) => {
    if (error) {
      const details = stderr || error.message || String(error);
      console.error('Chatbot error:', details);
      return res.status(500).json({ error: 'Failed to process AI chat query.', details: details });
    }

    const output = stdout ? stdout.toString() : '';
    const marker = '=== AI CHATBOT RESPONSE ===';
    let answer = output;
    if (output.includes(marker)) {
      answer = output.split(marker)[1].trim();
    }

    res.json({
      prompt,
      answer,
      rawOutput: output
    });
  });
});

// ─── Start ──────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`\n  ╔═══════════════════════════════════════════════════╗`);
  console.log(`  ║  Case Search Reports Demo                        ║`);
  console.log(`  ║  Server running at http://localhost:${PORT}          ║`);
  console.log(`  ╚═══════════════════════════════════════════════════╝\n`);
});
