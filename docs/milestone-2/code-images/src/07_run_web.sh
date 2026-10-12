# Live web version (tom-react-frontend) - Node 18+, Node 22+ for the Worker
git checkout tom-react-frontend
npm run install:all                # root + frontend
npm install --prefix cloudflare    # Worker

# comm demo: starts all 11 local processes and runs every mechanism
npm run comm:demo

# or run the full app with the React UI
./start-lodging.sh                 # services, hub, 3 subscribers, 3 replicas, UI

# tests
npm test                                                  # Node: 7 tests
BASE_URL=http://127.0.0.1:8787 npm run cf:test            # Worker under wrangler dev
BASE_URL=https://lodging.pitchblack.icu npm run cf:test   # live Worker: 20 checks
