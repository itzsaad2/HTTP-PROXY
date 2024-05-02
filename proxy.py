import socket
import time
import sys
import select
import os

def parseURL(full_url):
    #check and remove extra / at beginning of the relative URL, otherwise keep as is
    url = full_url[1:] if full_url.startswith('/') else full_url
    #the url is split into parts two parts at the first /, where the zeroth index is hostname
    url_parts = url.split('/', 1)
    hostname = url_parts[0]
    #the rest is then part of the path, first check if a path is suggested in the first place(i.e len(url_parts) > 1 meaning there is a hostname and path)
    #if there is no path suggested, then add / as the path and return the extracted hostname/path
    path = '/' + url_parts[1] if len(url_parts) > 1 else '/'
    return hostname, path

def AddHeaders(lines):
    #create a new dictionary to return
    head = {}
    # loop through each one of the headers, if a header exists then split from only the first occurance of : (as header value may aslo have :)
    for line in lines[1:]:
        if line:
            header_parts = line.split(': ', 1)
            #check if header in proper format(header name: header value)
            if len(header_parts) == 2:
                #if so then add it to the dictionary of headers
                head[header_parts[0]] = header_parts[1]
    return head

def parse_http_request(http_request):
    #do initial split to have the GET, hostname, path be seperate from the headers
    lines = http_request.split('\r\n')
    #make dictionary to hold headers
    headers = {}
    #lines[0] contains the GET, the URL and the http version, lines[1:] contains the headers 
    first_line = lines[0]
    #we split the request to get each part seperately(we only care about url)
    parts = first_line.split(' ')
    
    if len(parts) < 3:
        return None, None, None  # Invalid request format as either no GET, hostname/path, http version
    GET, full_url, http_version = parts
    #parse URL to get the hostname and path
    hostname, path = parseURL(full_url)
    #set up the headers dictionary
    headers = AddHeaders(lines)
    #return all the extracted information from the HTTP request
    print("\n---------------------------------------------------------------------------\n")
    print("the extracted hostname: " + str(hostname) + " , the extracted path: " + str(path))
    return hostname, path, headers

def makeheaderstring(hostname, headers):
    #make and add the hostname to headers(avoid bad request).
    headers['Host'] = hostname
    #create a list of all the header name: header value parings 
    headerlist = []
    for key, value in headers.items():
        headerlist.append(key + ":" + value)
    #join the whole list together to get a singular string for the header(make sure to seperate each header using \r\n)
    headers_string = '\r\n'.join(headerlist)
    print("\nthe string of headers is " + str(headers_string))
    return headers_string

def forward_http_request(client_conn, hostname, path, headers):
    try:
        #make a new socket connected to the website we are trying to visit
        websock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        #port 80 for http
        websock.connect((hostname, 80))
        
        #create a string combining all the headers
        headers_string = makeheaderstring(hostname, headers)
        #reconstruct the request line with the extracted values
        request_line = f"GET {path} HTTP/1.1\r\n{headers_string}\r\n\r\n"
        print("\nthe response we send back is " + str(request_line))
        #send the reconstructed request to the website socket to get back data
        #have to encode and decode in utf-8 for http
        websock.sendall(request_line.encode('utf-8'))

        #receive the repsonse/data from destination server
        response = b'' #initilize as byte string as we will be reading bytes
        #whie there is something to read, read it and store into response
        while True:
            chunk = websock.recv(4096)
            #if what we read is empty we can break(means there is nothing to read)
            if not chunk:
                break
            response += chunk
        #finally close the website socket once there is no more to read
        websock.close()

        #send the response from the website back to the client to load
        client_conn.sendall(response)
    #handle any exceptions rasied by printing them to the terminal
    except Exception as e:
        print("Something went worng during forwarding: " + str(e))

def proxy_server(port):
    #error check the argument lines
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("incorrect arguments. Please double check ")
        sys.exit()

    #extract the expiary time and current working directory(while file is) for the cache files
    exptime = int(sys.argv[1])
    directory = os.getcwd()
    #create socket, make it reuseable, bind to port 8888 and listen
    proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    proxy_socket.bind(('localhost', port))
    proxy_socket.listen(100)
    print("Proxy server listening on port " + str(port))

    #use Select.Select to monitor I/O for multiple connections
    #Took the example given from https://globaldev.tech/blog/working-tcp-sockets and modified it to my needs
    inputsocks = [proxy_socket]
    outputsocks = []
    #instead of a queue we will use a dictionary
    dataqueue = {}

    #monitor I/O of sockets(while there is a socket in inputsocks i.e new client)
    while inputsocks:
        readable, writable, exceptional = select.select(inputsocks, outputsocks, inputsocks)

        count = 0
        #loop through readable sockcets
        while(count < len(readable)):
            #if socket is our proxy socket then accept the connection
            if readable[count] is proxy_socket:
                connection, client_address = readable[count].accept()
                print("New connection from " + str(client_address))
                # make sure to set it to nonblocking to allow other connections to run as normal
                connection.setblocking(0)
                #append the new connection to the list of input sockets(socket we are waiting to hear back form)
                inputsocks.append(connection)
                dataqueue[connection] = b""  # Initialize message queue as byte string as we will be reading bytes
            else:
                # if the socket is not the proxy_socket then there is data to be read(from an exisiting client)
                data = readable[count].recv(4096)
                if data:
                    # read and store data in data queue and add to sockets ready to output(ready to write)
                    dataqueue[readable[count]] += data
                    if readable[count] not in outputsocks:
                        outputsocks.append(readable[count])
                else:
                    # No more data, prepare to close connection and remove socket from inputsock and outputsock, delete its dataqueue as well
                    if readable[count] in outputsocks:
                        outputsocks.remove(readable[count])
                    if readable[count] in inputsocks:
                        inputsocks.remove(readable[count])
                    if readable[count] in dataqueue:
                        del dataqueue[readable[count]]
                    readable[count].close()
            count +=1
    #iterate over sockets ready to send some data
        counter = 0
        while(counter < len(writable)):
            # retreive the data for the socket
            queue_data = dataqueue.get(writable[counter])
            if queue_data:
                #decode the data which is the HTTP requests
                http_request = queue_data.decode('utf-8')
                print("the request to parse is: " + str(http_request))
                #parse the HTTP request to get the hostname, path and dictionary of headers
                hostname, path, headers = parse_http_request(http_request)
                #forward the request back to the client
                forward_http_request(writable[counter], hostname, path, headers)
                # Clear the queue and close the connection after sending request to client(to allow receiving and processing new HTTP requests)
                dataqueue[writable[counter]] = b""
                if writable[counter] in outputsocks:
                    outputsocks.remove(writable[counter])
                if writable[counter] in inputsocks:
                    inputsocks.remove(writable[counter])
                writable[counter].close()
            #if there is no data then we can terminate the connection
            else:
                dataqueue[writable[counter]] = b""
                if writable[counter] in outputsocks:
                    outputsocks.remove(writable[counter])
                if writable[counter] in inputsocks:
                    inputsocks.remove(writable[counter])
                writable[counter].close()
            counter +=1



if __name__ == "__main__":
    proxy_server(8888)
