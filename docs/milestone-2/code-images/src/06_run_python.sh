# Python simulation (main branch) - Python 3.10+, standard library only
git clone https://github.com/haileyc1201/CECS327-Distributed-Lodging.git
cd CECS327-Distributed-Lodging

# start all 10 nodes as processes and run every mechanism
python3 -m src.communication.demo

# tests (10)
python3 -m unittest discover -s tests -t . -v

# or start each node in its own terminal
python3 -m src.communication.run property
python3 -m src.communication.run broker
python3 -m src.communication.run coordinator
python3 -m src.communication.run reservation
python3 -m src.communication.run subscriber notification-service   # + analytics-service, audit-service
python3 -m src.communication.run replica replica-1 6101            # + replica-2 6102, replica-3 6103
