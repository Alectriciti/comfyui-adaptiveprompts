# Adaptive Prompts


> - **17/08/25** Variables and Comments have been added. All nodes passed main stress-tests. Things are looking good so far!
> - **15/08/25** Established a somewhat working version of these nodes. It's stable enough to use.

## Introduction

Adaptive Prompts is a prompt crafting suite. It allows you to randomize, control, shuffle, and even program your prompts. Inspired by the legendary [Dynamic Prompts](https://github.com/adieyal/comfyui-dynamicprompts) by adieyal, which for many people is an essential tool, but hasn't been updated in quite some time.

Think of Adaptive Prompts as a distant relative Dynamic Prompts. You can expect the basic features to work as you know them to, but it is  {For the sake of familiarity|In honor of a new chapter} I will ambiguously refer to this system as { Adaptive | Dynamic } Prompts.


# ⚡ Quick Node Reference 

## Generation Nodes
These nodes generate new content in your prompt, either by utilizing dynamic prompt syntax, or some other method of generation.

>In these descriptions, a "phrase" can be defined as the space between two commas: *"masterpiece, **this is a phrase**, low quality"*


| Node | Description | Note |
|------|---------|-------|
| 💡 Prompt Generator | Creates dynamic prompts based on your input. Use {brackets} or \_\_wildcards\_\_ | Originally "Random Prompts" |
| 📦 Prompt Repack | A powerful inverse of Prompt Generator. It converts natural words, tags, or phrases back into wildcards. | New/Experimental |
| 🔁 Prompt Replace | Search & Replace, but on steroids. Both inputs support dynamic prompts, then apply procedurally. | New/Experimental |
| 📚 Prompt Alias Swap | Utilizes a tag_alias.txt file, tags separated by commas in this file will be automatically swapped out randomly. | Does not yet support .csv  |

## Processing Nodes
| Node | Description | Note |
|------|---------|-------|
| 🏋️‍♀️ Weight Lifter | Randomly or procedurally applies weights to phrases, "(epic masterpiece:1.105), (highres:0.925)" |  |
| ✂️ Prompt Trimmer | Remove or keeps sections of a prompt based on various algorithms. | |
| 🥣 Prompt Mix | Takes two prompts and mixes them together with a variety of methods. Useful for sprinkling in processed tags/phrases. | |
| ♻️ Prompt Shuffle | Randomly shuffles phrases with a limit on how many are shuffled. Lightweight and fast. | |
| ♻️ Prompt Shuffle (Advanced) | Utilizes techniques such as walking, rather than arbitrarily shuffling the phrases. Useful for subtle variance. | |
| 🧹 Prompt Cleanup | A very simple multi-tool. Tidies up prompts, such as removing whitespace, extra commas, lora tags, etc. Usually last in the node chain. | |

## Utility Nodes
| Node | Description | Note |
|------|---------|-------|
| 🔗 String Append | Combines multiple strings into one using a specified separator. Comes in a 3 and 8 version. | |
| ⛓️‍💥 String Split | Directly splits a prompt into 3 parts to isolate a middle section using start and end. | |
| 🟰 Normalize Lora Tags | Provides lora weight control by normalizing the values of lora tags. Allowing for flexible inputs. | used w/ Lora Tag Loader |
| 🖼️ SaveImageAndText | Comfy's Image Saver, but saves a .txt file with contents of your choosing. Intended for saving the resulting prompt. | |




Combining these various nodes can result in highly creative prompts.

# Dynamic Prompting Quickstart Guide
> *(This does not mention new features, so feel free to skip this section if you're already familiar with dynamic prompts)*
<details>
  <summary><b>Quickstart Guide</b></summary>
  
  
### Basic Example
There are two primary methods to randomize a prompt:

1. **Brackets:** ```{red|green|blue}``` randomly chooses between "red", "green", and "blue"
2. **Wildcards:** ```__fruit__``` chooses a random line from a .txt file called "fruit.txt"

**/wildcards/fruit.txt Example:**
```
# comments can be applied like this
apple
orange
banana

# brackets work here too, effectively making the options less common
{strawberry|blueberry}

# the more options you add, the less likely you'll roll that option
{kiwi|mango|pineapple|pomegranate}

# wildcards can even call other wildcards, allowing for recursion
__fruit_exotic__
```

These two powerful methods can be combined to build very dynamic prompts. Here's a simple example of what can be done:

**Example Input:** ```masterpiece, {2$$__shot__|__canvas__}, __scene_forest__, __quality__```

**Example Output:** ```masterpiece, blue canvas, wideshot, magnificent forest with willow trees with a patch of grass and daffodils, blueberry bush, high-quality, highres```


To see what's going on here, take a look at how dynamic prompts handles unwrapping these nested brackets and wildcards:

**Processing Stage 1:** ```masterpiece, __color__ canvas, wideshot, __adj__ forest with {2-3$$ and $$__plants__|__trees__|__grass__}, high-quality, highres```

**Processing Stage 2:** ```masterpiece, blue canvas, wideshot, __wonderful__ forest with willow trees and a patch of grass and __flowers__, __bush__, high-quality, highres```

Processing Stage 3 is not required because everything has been unwrapped.

Notice how wildcards can be nested within wildcards. It's all up to how you structure your bracket options and wildcards.

Here's an alternate Result Example when using that very same input example: ```masterpiece, closeup shot, pink canvas, excellent shaded forest with cherry-blossom trees, rocks along a cliffside, shaded forest, godrays, gravel path leading to a cave, riverbed, colorgraded, best quality```

### 🔢 Multiple Choices within Brackets
Multiple selections can be made using this syntax:
```
{5$$__fruit__}
{2-4$$__animal__|__color__}
```
Line 1 could be read as instruction: ```pull 5 random lines from fruit.txt```
Line 2 could be read as instruction: ```pull 2 to 4 random lines from animal.txt and bird.txt```

Example Result:
```
apple, mango, kiwi, orange, banana
cat, green, dog
```

If you don't want a comma and space between each selection, you can use your own custom separator using the following syntax:
```
{3-5$$ $$__fruit__}
{3$$ and $$__animal__}
```

Example Result:
```
apple banana kiwi strawberry
sheep and cat and dog
```

### 📁 Wildcard Random Selection and Subfolders

Wildcards can be even more randomized with glob matching by utilizing the * symbol. Here's an example. Say you have the following folder structure within /wildcards/:

```
lighting.txt
lighting_dim.txt
lighting_bright.txt
```

By calling ```__lighting*__``` it will pick one of those three files to draw a prompt from. Furthermore, if you want to bypass the original ```lighting.txt```, you can type ```__lighting_*__``` to ensure that only the two latter are selected. This function can be read as ```select any wildcard in this folder that starts with "lighting_"```

Wildcards can also be be nested in subfolders. ```/wildcards/environments/cave.txt``` can be called with ```__environments/cave__```. One primary advantage of this is that it can help with organization for certain themes. Not only that, using a * expression works here, but restricts to only that folder. ```__environments/*__``` will select *any* wildcard in the /environments/ folder.
Yes, this also means you can use the wildcard ```__*__```. I don't recommend this unless you prefer chaos.

Yes, the possibilities are endless. And these are just the basics of what can be done with dynamic prompts.

> This is the extend of what is currently supported *as of August 16, 2025*.

</details>



# New Features and Nodes



## 💡 Prompt Generator

<img src="images/prompt_generator_variables_example.png"/>

Formerly known as **Random Prompts**, this is the essential component to dynamic prompting.

It works mostly like you remember, but there are a few twists

### Wildcards Refresh Instantly
No more having to restart ComfyUI every time you make a change to wildcards.

### Brackets Wildcards no longer limit length
Before, doing ```{4-5$$__shape__|__color__}``` would restrict the output to only 2, such as ```square, green```.
This is no longer the case. The contents of brackets will always adhere to the length you specify!

### Lora tags with "weird__underscores" no longer break syntax

Dynamic prompts no longer completely derail simply because of an unfortunate naming convention by a lora. *cough cough*. So `<lora:coolest__lora__ever__:1.0>` will not break things.

## Separator Syntax

Dynamic separators are now possible, by allowing for recursion in that text space. Example:

```{4$$ __and__ $$bob|bertha|benny|bella}``` -> ```bertha with benny and bob plus bella```

Let's say that **and.txt** contains the following:
```
and
with
or
```

Then we use that wildcard as the separator token for a bracket wildcard:
```
{3-4$$ __and__ $$A|B|C|D|E}
```

example outputs:
```
A or E and B
C and D with B or A
B with C and D
```

This opens up possibilities for expanding bracket prompts. ```{2-3$${,| }$$this|works|too}```


### ⚖️ Chance Weights

A very simple chance weighting system is included.
It's not very fleshed out right now, and probably buggy as hell. But it gets the job done.
Here's a `chance.txt` wildcard example:

```
# the %% tokens can be placed in front or behind depending on your preference
%80% common
%10% uncommon
rare  # default is 1
ultrarare %0.1%
```

### #️⃣ Comments

Comments can be placed inside of prompts. This could be useful to make note of various tags or ideas you want to tinker with.

Input: ```##  Hehehe I'm so sneaky...## Huh, must have been the wind.```

Output: ```Huh, must have been the wind.```

## ⚡Variables

Variables can be assigned and accessed in a few different ways. They can even be accessed from within wildcards. They can technically be set within wildcards, but i wouldn't recommend it due to how the ordering is done.

### ✏️ Variable Assignment 
```
## {variables|can|be|assigned|like|this}^alpha ##
## or can be assigned like this: __character^awesome__ ##

Note: the comment blocks not only prevent the resulting text from being included in the output,
but ensure they are calculated before the rest of the prompt is executed.
this is technically a limitation, but also a feature. you can run it without the comment blocks, but variable retrievals might return nothing.
```

### 🔍 Variable Retrieval
```
Now that we've initialized our variables, we can retrieve them like this:
__^alpha__, __^awesome__,
we can use glob matching with * since they both start with the letter 'a':
__^a*__
We could even randomly retrieve any assigned variable in this prompt instance:
__^*__
With this in mind, clever variable naming conventions could go a long way.
```


### 🔗 Linked Variables
If you so desire, you can assign multiple values to the same variable. Retrieving them allows for further randomization.
```
First, assign the variables:
__character^x__
__color^x__
__fruit^x__

Now calling that variable will retrieve one of the results randomly:
{3$$__^x__}
Example Output: Yellow, Kermit, Apple
```

### 💎 Unique Variables
You can ensure unique variables in one go *(currently only supported by bracket wildcards)*
```
You can assign multiple variables which are guaranteed to have unique results:
{calvin|braxis|celia|deku|esther}^char1^char2^char3

By doing this, we now have 3 variables each with unique assignments!
For example:
__^char1__ = celia
__^char2__ = deku
__^char3__ = calvin

Great for randomized story/scenario prompts.
```

> **Important:** When assigning variables, I strongly recommend placing them in a ```## comment space like this ##```. This is because the Prompt Generator seeks out comment lines and executes the brackets/wildcards in there first. If you don't do this, things might work, but depending on the complexity of your prompt, you variable retrievals might yield null.

---


## 📦 Prompt Repack
<img src="images/prompt_repack_example.png"/>

Prompt Repack is an experimental node which can be thought of as the inverse of Prompt Generation. It encapsulates keywords with a wildcard file they exist in. This allows for semantic driven dynamic prompting and even more brainstorming.

A good example of how powerful this system can be is the word "chicken". It belongs to both ```__animal__``` and ```__food__``` wildcards. This can lead to some pretty creative results when rewrapping it.

Prompt Repack has the following modes. In order to explain them, keep this context in mind: ```, this is a phrase and this_is_a_tag, ...```
- **Per Word**
  > Only targets words separated by whitespace. Extremely fast and lightweight. 
- **Per Phrase**
  > Only targets phrases separated by commas but only if it equals exactly. This can be tags or phrases, but it has to match exactly. Pretty solid if you're only building simple prompts where each phrase or tag is separated by a comma.
- **Both**
  > Combines the above methods: 1. Detect Phrase 2. Do a second pass to detect remaining words.
- **Both With Tags**
  > Same as above, but will also attempt matching the tags. It does this by replacing the entire phrase's whitespace with underscores, then attempts matching. Not very well tested but thought I'd leave it in.
- **Detect All**
  > Extremely aggressive and the most computationally demanding. It attempts finding phrases through various methods, see above image example.


The purpose of this node is to allow you to write with natural language, then wrapping it in a dynamic and creative way.

Many users have wildcards for everything, even simple phrasing. I personally have an ```__and__``` tag which I use as a separator token. However, when utilizing Prompt Rewrap
The blacklist file is a list of words or wildcards you want this system to ignore.

**Current Limitations (as of 18/08/2025)**: It currently only supports drawing a wildcard if the matched phrase/word equals the line in the wildcard file. In other words: provide the string: ```harry_potter and luke_skywalker```
```
# /wildcards/character.txt
luke_skywalker
{harry_potter|ron_weasly}
```
The result would be: ```harry_potter and __character__```
This is planned to be fixed.

>**Warning:** If you have wildcards with extremely long names,

> Note: Prompt Rewrap pre-caches for faster lookups on startup. So if changes are made to wildcards, you'll have to restart ComfyUI.


## 🔁 Prompt Replace
<img src="images/dynamic_replacement.png"/>

Acts as a standard String Replace function, with a twist. The search string and replace string both accept wildcards.

**String** - The input string to process
```
the quick brown fox jumped over the lazy dog
```

**Search** - performs multiple searches based on new lines
```
fox
dog
```

**Replace** - calculates dynamic prompts for each replacement action, this can be brackets or wildcards
```
{1-2$$ and $$__animal__}
```

Example Result:
```
the quick brown cow and pig jumped over the lazy cat
```


  - Can be used as a regular Search and Replace
  - Allows for multi-line inputs for searching, allowing for many different keywords to be swapped out in one go.


# 🏋️‍♀️ Weight Lifter

An experimental node to shuffle up the weights on your nodes.

 ```this text is not strong, it is weak, it needs srs gainz```
 --->
 ```(this text is not strong:1.08), (it is weak:1.16), (it needs srs gainz:1.27)```


# 🛠️ Extra Utilities

>These are simple but useful nodes that can apply to most comfy workflow, and can serve as powerful post-processing nodes for adaptive prompts.

## ♻️ **Prompt Shuffle**
  - A very simple shuffler which can randomize ordering of a prompt.
  - Unlike the advanced version, the ```limit``` parameter limits the number of tags output.
## ♻️ **Prompt Shuffle (Advanced)**
  - Similar function as above, but utilizes logic to shuffle the tags, which helps greatly with the decaying emphasis nature of prompts.
  - WALK allows tags to travel per action, utilize decay, and many other things.
## 🧹 **Prompt Cleanup**
<img src="images/prompt_cleanup_example.png"/>

A simple prompt swiss-army knife. Sometimes, dynamic prompts get messy. This little guy can help clean them up.
  - Can remove excess commas
  - Can remove excess whitespace
  - Can remove lora tags that may have slipped by other processors.
  - Can remove remove stray parenthesis, square brackets, or both.
  - Can replace newlines with space or commas
## 🟰 **Normalize Lora Tags**
  - Worry less about the oversaturation of lora tags with this node which helps normalize the values automatically.
  - Positive and Negative values can be assigned independently or combined.
  - Lora Tag Parser. I recommend: [Lora Tag Loader by badjeff](https://github.com/badjeff/comfyui_lora_tag_loader)
## **String Merger**
  - A lightweight merger for strings
  - Has a (4) version and a (12) version
  - Combines strings separated with a new-line.




# 💡 Tricks & Tips


## Randomized Lora Weights
A neat trick i've been using for awhile is placing a weighted wildcard as the weight of a lora. ```<lora:cool_lora:__weight__>``` Like this. This is a useful way to establish randomized lora weights.
This works well if you're using [Lora Tag Loader](#Links).
And it works even better now with the Normalize Lora Tags node.

rlow.txt:
```
# Random Low Weights
0.05
0.1
0.15
0.2
0.25
0.3
```

Then I run this through the prompt generator:
```
<lora:funny_dog:__rlow__>
```
This allows for wildcards and prompts to handle loras for you.
Consider combining this with the Lora Tag Normalizer.

# Links

  ### [🐍 Custom Scripts by pythongosssss](https://github.com/pythongosssss/ComfyUI-Custom-Scripts)
  Provides a handful of useful nodes. Honestly, a must-have. These are ones I use often:
  - Show Text (simple and practically essential)
  - String Function (for appending or replacing strings)
  - Image Feed (for displaying results)
  ### [Lora Tag Loader by badjeff](https://github.com/badjeff/comfyui_lora_tag_loader)
  This loads loras using the classic ```<lora:sharpness_enhancer:1.0>``` syntax, providing a model and clip node, as well as preserving the string. Works excellently with dynamic prompts.

# Installation

Install like any other ComfyUI Node pack. Download the Zip and place in ```/ComfyUI/custom_nodes/```

## Disclaimers

This project is a proof of concept and experimental. 

I've been programming for quite a long time and have a good understanding off logical flow and optimization, but I am not very experiened with python. The code works, so take that for what you will.

I have no plans to adapt this to any other UI, as dynamic-prompts for A1111. It didn't need it. It's far more efficient and useful than ComfyUI's implementation.

---

Created by **Alectriciti** | 🎵 [Check out my music](https://open.spotify.com/artist/1gjzBsWjtl4yBmVYWB8vbc) 