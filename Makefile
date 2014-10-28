# This the Tango makefile. It documents how to run and build the system

default:
	@echo "Call me with a specific rule"

# This rule runs the tango server.
startTango:
	(nohup ./startTangoREST.sh &> tango3.out &)

clean:
	rm -f *~
