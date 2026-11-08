# Decisions

## What I tried

## What I chose and why

## What I'd do next

## What I deliberately didn't do

Hey, just read that this file has a template, I wrote unstructured thoughts in another doc and am just reading this with ~3 minutes left. Sorry about that and I hope this is acceptable.


First thoughts after reading the writeup is that the main leverage for speed it to parallelize the API requests in a way that doesn’t include errors through things like rate limiters.

My first attempt / iteration will be just running the API’s with asyncio with 10 concurrent tasks

I just gave CODEX the instructions to use asyncio to run the API’s in parallel. Once it is completed I’ll look at the completed code and then run it to see the results.

Each make run takes a while, I will have to be conservative with my runs to not take too much time. I could also store the time taken for each call in the notes so that I can iterate on only those clips that are short or take too much time.

If I’m trying to maximize the correct number of outputs completed in 900 seconds, I could just calculate the max number of time given to each clip before it is timed out. 900 seconds for 142 examples with 10 concurrent requests running is 9000 / 142 = ~63.38. 

Running 10 concurrent requests led to frequent “Too Many Requests” errors. Reduced the concurrent requests for asyncio to 4. Codex implemented staggered retries.

If this new codex run doesn’t work I’m going to stop the run and implement more structured problem solving to determine exactly what is going wrong.

Codex completed, I ran “make evaluate” and 6 of the requests did not have a complete alignment. Currently going over the cause of these errors from the output

 "clip_0025": {
   "text": "Oh. So what's the right setting? Because it's really weird. It's like, it's like at regular intervals vertically. I was watching a horror movie last night. A regular intervals vertically, you can see like the left side of the darkness is lighter and then it gets darker and then it gets to a new panel and it's light again. So there's like a regular gradient. And you know, this is at night we were watching this so I don't know what was wrong with the conditions.",
   "status": "ok",
   "alignment": []
 },

Some clips just did not get a response from alignment. For example clip_0025, 0056, 0110, 0122, 0123, 0124. Here are some possible reasons and solutions for this:




Reason			Solution
Wrong input			we sent an empty transcript to the server
Rate limiting			fix retry logic or create a queue of failures to retry at the end
Genuine Failure		the server provides an empty list as response (can’t fix)


I’m creating a toy script that runs the API on the requests that failed. If they continue to fail in a synchronous environment then we know that the errors are likely due to the genuine API responses being incorrect. Otherwise they are likely due to rate limiting or wrong inputs from us. If it is due to failed async logic then I will evaluate our code and find the solution using Codex.

This test demonstrated that the model occasionally returns an empty alignment list with the correct input. I’ve implemented logic for retries given this empty response. Given that it produced 6 errors in 142 responses it seems the error rate is 6/142 = 4.23%, so assuming the errors are IID across all trials, then given 3 retries there is a .0423 ^ 3 chance that a request is still empty after three retries.

It’s 1:22, I have 42 minutes left to run and evaluate my final result for the main part. As make run is going I will look into the bonus portion.

Make run is completed and passes everything taking 378s / 900s

Note on code quality: normally I would dive into the code and add comments / fix variables as necessary before submission. I’m not incredibly familiar with asyncio however and what exactly good code quality means in this toy repo thus I think it would be more beneficial to move onto the bonus question. I did however clean up some of the unnecessary changes that codex made.

Chunks.json:

There seems to be two questions on chunks.json:
What boundary to choose for words
How To Implement This

For the boundary question I think a good boundary might be every 10 words, with the end time of a sequence being the average of the last word of sequence one and the start of the next sequence. The last sequence for each clip will just be the remaining n % 10 words. 

For the implementation question I think just make it so that as elements are added to output.json, run a chunking algorithm on them and add that result to chunk.json 

After thinking about this I don’t really have time, but I commented out some code for my planned implementation that would likely work but I don’t have time to test before submission.